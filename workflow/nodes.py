"""
LangGraph node functions.

Each function takes an AppState dict and returns a (partial) AppState dict.
They are intentionally pure/sync — the graph runner calls them in a thread.
"""
import glob
import io
import os
import time
from typing import TypedDict, Optional

import requests
from bs4 import BeautifulSoup
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai
from dotenv import load_dotenv
from core.config import get_settings

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv(dotenv_path="./.env.local")

# Remove global API key config


# ---------------------------------------------------------------------------
# Shared state type
# ---------------------------------------------------------------------------
class AppState(TypedDict):
    url: str
    content_type: Optional[str]  # "youtube" | "blog" | "media" | "upload"
    title: Optional[str]
    extracted_text: Optional[str]
    audio_file_uri: Optional[str]
    error: Optional[str]
    notes: Optional[str]
    source_type: Optional[str]
    gemini_api_key: str
    # Upload-specific fields
    upload_content_type: Optional[str]  # "video" | "audio" | "text" | "document"
    file_bytes: Optional[bytes]
    filename: Optional[str]


# Media file extensions for direct URL detection
_MEDIA_EXTENSIONS = {
    # Audio
    ".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac", ".wma",
    # Video
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".ts",
}

# Extension → MIME type mapping (used for Gemini uploads)
_EXT_TO_MIME = {
    ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac",
    ".aac": "audio/aac", ".wma": "audio/x-ms-wma",
    ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
    ".mov": "video/quicktime", ".webm": "video/webm", ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv", ".ts": "video/mp2t",
}

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac", ".wma"}


def _get_url_extension(url: str) -> str:
    """Extract the file extension from a URL, ignoring query parameters."""
    from urllib.parse import urlparse
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower()


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def route_url(state: AppState) -> AppState:
    url = state.get("url", "")
    if state.get("upload_content_type"):
        return {**state, "content_type": "upload", "source_type": "upload"}
    if "youtube.com" in url or "youtu.be" in url:
        return {**state, "content_type": "youtube", "source_type": "youtube"}
    # Detect direct audio/video file URLs
    ext = _get_url_extension(url)
    if ext in _MEDIA_EXTENSIONS:
        source = "audio" if ext in _AUDIO_EXTENSIONS else "video"
        return {**state, "content_type": "media", "source_type": source}
    return {**state, "content_type": "blog", "source_type": "article"}


def extract_blog(state: AppState) -> AppState:
    try:
        url = state["url"]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        print(f"Fetching blog content with BeautifulSoup from: {url}")
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "svg", "form"]):
            element.decompose()

        title = soup.title.string if soup.title else "Blog Post"
        text = soup.get_text(separator=" ", strip=True)

        if not text or len(text) < 100:
            return {**state, "error": "Not enough readable content found on this page."}

        # Limit text length just in case
        return {**state, "extracted_text": text[:100_000], "title": title}
    except requests.exceptions.Timeout:
        return {**state, "error": "Request to the blog URL timed out. The site might be too slow."}
    except Exception as e:
        return {**state, "error": f"Failed to extract blog content: {str(e)}"}


def _pick_best_audio_format(formats: list) -> str:
    """Pick the best audio format from available yt-dlp formats.
    
    Preference order:
    1. Audio-only streams, preferring m4a > webm > mp3 > others, sorted by bitrate
    2. Any format that has audio (video+audio combined), sorted by audio bitrate
    3. Fallback to 'bestaudio/best' and let yt-dlp figure it out
    """
    # Separate audio-only formats from combined formats
    audio_only = []
    has_audio = []
    
    preferred_exts = {"m4a": 0, "webm": 1, "mp3": 2, "ogg": 3, "opus": 4}
    
    for fmt in formats:
        fmt_id = fmt.get("format_id", "")
        ext = fmt.get("ext", "")
        abr = fmt.get("abr") or fmt.get("tbr") or 0  # audio bitrate or total bitrate
        vcodec = fmt.get("vcodec", "none")
        acodec = fmt.get("acodec", "none")
        
        # Skip formats with no audio
        if acodec == "none" or acodec is None:
            continue
        
        # Audio-only: no video codec
        if vcodec == "none" or vcodec is None:
            ext_priority = preferred_exts.get(ext, 99)
            audio_only.append((ext_priority, -abr, fmt_id, ext))
        else:
            has_audio.append((-abr, fmt_id, ext))
    
    if audio_only:
        audio_only.sort()  # sort by ext priority, then by -abr (highest first)
        chosen_id = audio_only[0][2]
        chosen_ext = audio_only[0][3]
        print(f"[YouTube] Found {len(audio_only)} audio-only formats; picking '{chosen_id}' ({chosen_ext})")
        return chosen_id
    
    if has_audio:
        has_audio.sort()  # sort by -abr (highest bitrate first)
        chosen_id = has_audio[0][1]
        chosen_ext = has_audio[0][2]
        print(f"[YouTube] No audio-only formats; picking combined '{chosen_id}' ({chosen_ext})")
        return chosen_id
    
    print("[YouTube] WARNING: Could not identify any audio format, falling back to 'bestaudio/best'")
    return "bestaudio/best"


def extract_youtube(state: AppState) -> AppState:
    url = state["url"]
    settings = get_settings()
    video_id: Optional[str] = None

    if "v=" in url:
        video_id = url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        video_id = url.split("youtu.be/")[1].split("?")[0]

    if not video_id:
        return {**state, "error": "Invalid YouTube URL — could not extract video ID."}

    # --- Try transcript first (fast path) ---
    try:
        # Note: YouTubeTranscriptApi can also take cookies, but usually transcript block
        # is less aggressive than the media download block.
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join([t["text"] for t in transcript])
        return {**state, "extracted_text": text, "title": "YouTube Video Notes"}
    except Exception as transcript_err:
        print(f"Transcript unavailable ({transcript_err}), falling back to audio download…")

    # --- Audio fallback ---
    cookie_file = None
    try:
        # If user provided cookies as a string, write to a temp file for yt-dlp
        cookies_provided = False
        if settings.YOUTUBE_COOKIES:
            cookie_str = settings.YOUTUBE_COOKIES
            # Environment variables often store literal \n instead of real newlines
            if "\\n" in cookie_str and "\n" not in cookie_str:
                cookie_str = cookie_str.replace("\\n", "\n")
            
            cookie_file = f"cookies_{video_id}.txt"
            with open(cookie_file, "w", encoding="utf-8") as f:
                f.write(cookie_str)
            
            # Validate basic structure
            lines = [l.strip() for l in cookie_str.strip().splitlines() if l.strip() and not l.startswith("#")]
            cookies_provided = True
            print(f"[YouTube] Cookies file written with {len(lines)} cookie entries")
            if lines:
                # Each Netscape cookie line should have 7 tab-separated fields
                sample = lines[0]
                fields = sample.split("\t")
                if len(fields) != 7:
                    print(f"[YouTube] WARNING: Cookie format looks wrong — expected 7 tab-separated fields, got {len(fields)}")
                    print(f"[YouTube] Sample line: {sample[:100]}...")
        else:
            print("[YouTube] No YOUTUBE_COOKIES environment variable set")

        output_template = f"temp_{video_id}"
        base_ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        
        if cookie_file:
            base_ydl_opts["cookiefile"] = cookie_file
        
        if settings.YOUTUBE_PROXY:
            base_ydl_opts["proxy"] = settings.YOUTUBE_PROXY

        # Step 1: Query available formats (no download)
        info_opts = {**base_ydl_opts, "skip_download": True}
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        title = info.get("title", "YouTube Video")
        formats = info.get("formats", [])
        
        # Step 2: Pick the best audio format from available ones
        chosen_format = _pick_best_audio_format(formats)
        print(f"[YouTube] Selected format: {chosen_format}")

        # Step 3: Download with the chosen format
        dl_opts = {
            **base_ydl_opts,
            "format": chosen_format,
            "outtmpl": f"{output_template}.%(ext)s",
        }

        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            dl_info = ydl.extract_info(url, download=True)
            ext = dl_info.get("ext", "m4a")
            filename = f"{output_template}.{ext}"
        
        # Fallback: if the expected filename doesn't exist, glob for it
        if not os.path.exists(filename):
            candidates = glob.glob(f"{output_template}.*")
            if candidates:
                filename = candidates[0]
                print(f"[YouTube] Actual downloaded file: {filename}")
            else:
                raise FileNotFoundError(f"Downloaded file not found for {output_template}")

        print(f"Uploading {filename} to Gemini...")
        genai.configure(api_key=state["gemini_api_key"])
        
        # Map file extension to MIME type for Gemini
        ext_to_mime = {
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".mp4": "audio/mp4",
            ".webm": "audio/webm",
            ".ogg": "audio/ogg",
            ".opus": "audio/ogg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".aac": "audio/aac",
        }
        file_ext = os.path.splitext(filename)[1].lower()
        mime_type = ext_to_mime.get(file_ext, "audio/mp4")
        print(f"[YouTube] Using MIME type: {mime_type} for extension: {file_ext}")
        
        gemini_file = genai.upload_file(path=filename, mime_type=mime_type)

        while gemini_file.state.name == "PROCESSING":
            print("Waiting for Gemini file processing…")
            time.sleep(2)
            gemini_file = genai.get_file(gemini_file.name)

        if os.path.exists(filename):
            os.remove(filename)

        return {**state, "audio_file_uri": gemini_file.name, "title": title}
    except Exception as audio_err:
        error_msg = str(audio_err)
        if "Sign in to confirm you're not a bot" in error_msg or "bot" in error_msg.lower():
            if cookies_provided:
                error_msg = ("YouTube blocked the request even WITH cookies provided. "
                             "The cookies are likely expired or malformed. Please re-export "
                             "fresh Netscape-formatted cookies from a browser where you are "
                             "logged into YouTube and update the 'YOUTUBE_COOKIES' env var.")
            else:
                error_msg = ("YouTube blocked the server's IP. Please provide Netscape-formatted cookies "
                             "in the 'YOUTUBE_COOKIES' environment variable to bypass this.")
        return {**state, "error": f"Could not extract audio or transcripts: {error_msg}"}
    finally:
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)


def extract_media_url(state: AppState) -> AppState:
    """Download a direct audio/video URL and upload to Gemini for transcription."""
    url = state["url"]
    ext = _get_url_extension(url)
    mime_type = _EXT_TO_MIME.get(ext, "audio/mpeg")
    source_type = "audio" if ext in _AUDIO_EXTENSIONS else "video"

    try:
        print(f"[Media URL] Downloading {source_type} from: {url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=120, stream=True)
        response.raise_for_status()

        # Determine filename
        from urllib.parse import urlparse
        url_path = urlparse(url).path
        basename = os.path.basename(url_path) or f"media{ext}"
        tmp_path = f"media_dl_{os.getpid()}_{basename}"

        # Stream to disk
        total = 0
        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                total += len(chunk)
        print(f"[Media URL] Downloaded {total // 1024} KB")

        # Upload to Gemini
        genai.configure(api_key=state["gemini_api_key"])
        print(f"[Media URL] Uploading to Gemini with mime_type={mime_type}")
        gemini_file = genai.upload_file(path=tmp_path, mime_type=mime_type, display_name=basename)

        while gemini_file.state.name == "PROCESSING":
            print("[Media URL] Waiting for Gemini file processing…")
            time.sleep(2)
            gemini_file = genai.get_file(gemini_file.name)

        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        return {**state, "audio_file_uri": gemini_file.name, "title": basename,
                "source_type": source_type}

    except requests.exceptions.Timeout:
        return {**state, "error": "Download timed out. The media file may be too large or the server too slow."}
    except Exception as e:
        return {**state, "error": f"Failed to download media from URL: {str(e)}"}


def extract_upload(state: AppState) -> AppState:
    """Handle uploaded content: raw text, video/audio file, or PDF/DOCX document."""
    upload_type = state.get("upload_content_type", "text")
    file_bytes: Optional[bytes] = state.get("file_bytes")
    filename: Optional[str] = state.get("filename") or "upload"

    try:
        if upload_type == "text":
            text = state.get("extracted_text", "")
            if not text or len(text) < 50:
                return {**state, "error": "Pasted text is too short to generate notes."}
            return {**state, "title": "Pasted Document", "source_type": "document",
                    "extracted_text": text[:200_000]}

        elif upload_type in ("video", "audio"):
            if not file_bytes:
                return {**state, "error": f"No {upload_type} file received."}
            # Write to a temp file then upload to Gemini File API
            _, ext = os.path.splitext(filename)
            if not ext:
                ext = ".mp4" if upload_type == "video" else ".mp3"
            mime_type = _EXT_TO_MIME.get(ext.lower(), "audio/mpeg" if upload_type == "audio" else "video/mp4")
            tmp_path = f"upload_{upload_type}_{os.getpid()}{ext}"
            try:
                with open(tmp_path, "wb") as f:
                    f.write(file_bytes)
                print(f"Uploading {upload_type} ({len(file_bytes) // 1024} KB) to Gemini…")
                genai.configure(api_key=state["gemini_api_key"])
                gemini_file = genai.upload_file(path=tmp_path, display_name=filename, mime_type=mime_type)
                while gemini_file.state.name == "PROCESSING":
                    print(f"Waiting for Gemini file processing…")
                    time.sleep(2)
                    gemini_file = genai.get_file(gemini_file.name)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            return {**state, "audio_file_uri": gemini_file.name, "title": filename,
                    "source_type": upload_type}

        elif upload_type == "document":
            if not file_bytes:
                return {**state, "error": "No document file received."}
            lower = filename.lower()
            text = ""
            if lower.endswith(".pdf"):
                try:
                    import pypdf
                    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                    text = "\n".join(
                        page.extract_text() or "" for page in reader.pages
                    )
                except ImportError:
                    # Fallback to PyPDF2
                    import PyPDF2
                    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    text = "\n".join(
                        reader.pages[i].extract_text() or ""
                        for i in range(len(reader.pages))
                    )
            elif lower.endswith(".docx"):
                try:
                    import docx
                    doc = docx.Document(io.BytesIO(file_bytes))
                    text = "\n".join(p.text for p in doc.paragraphs)
                except ImportError:
                    return {**state, "error": "python-docx is not installed on the server."}
            elif lower.endswith(".txt"):
                text = file_bytes.decode("utf-8", errors="replace")
            else:
                return {**state, "error": f"Unsupported document format: {filename}"}

            if not text or len(text.strip()) < 50:
                return {**state, "error": "Could not extract readable text from the document."}
            return {**state, "extracted_text": text[:200_000], "title": filename,
                    "source_type": "document"}

        else:
            return {**state, "error": f"Unknown upload type: {upload_type}"}

    except Exception as exc:
        return {**state, "error": f"Failed to process upload: {str(exc)}"}


def generate_notes(state: AppState) -> AppState:

    print("--- Actual note creation started ---")
    if state.get("error"):
        return state

    if not state.get("gemini_api_key"):
        return {**state, "error": "Gemini API key is not configured for this user."}

    try:
        genai.configure(api_key=state["gemini_api_key"])
        model = genai.GenerativeModel("gemini-3-flash-preview")

        prompt = f"""
You are an expert educational assistant. Create clear, highly-structured, easy-to-read revision notes
based ONLY on the provided content.

Source Title: {state.get('title', 'Content')}

Format your response in Markdown:
1. H1 heading with the title.
2. **Quick Summary** (2-3 sentences).
3. **Key Concepts** section as an unordered list.
4. Main topics as H2 headings with bullet points, bold text, and brief paragraphs.
5. **Important Takeaways / Conclusion** at the end.

Be concise but comprehensive. No conversational filler — just the notes.
"""
        contents = [prompt]

        if state.get("extracted_text"):
            contents.append(state["extracted_text"])
        elif state.get("audio_file_uri"):
            gemini_file = genai.get_file(state["audio_file_uri"])
            contents.append(gemini_file)
        else:
            return {**state, "error": "No content available to generate notes from."}

        response = model.generate_content(contents)

        # Clean up remote file
        if state.get("audio_file_uri"):
            try:
                genai.delete_file(state["audio_file_uri"])
            except Exception:
                pass  # Non-fatal

        return {**state, "notes": response.text}
    except Exception as e:
        return {**state, "error": f"AI generation failed: {str(e)}"}
