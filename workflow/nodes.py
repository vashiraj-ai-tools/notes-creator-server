"""
LangGraph node functions.

Each function takes an AppState dict and returns a (partial) AppState dict.
They are intentionally pure/sync — the graph runner calls them in a thread.
"""
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
    content_type: Optional[str]  # "youtube" | "blog" | "upload"
    title: Optional[str]
    extracted_text: Optional[str]
    audio_file_uri: Optional[str]
    error: Optional[str]
    notes: Optional[str]
    source_type: Optional[str]
    gemini_api_key: str
    # Upload-specific fields
    upload_content_type: Optional[str]  # "video" | "text" | "document"
    file_bytes: Optional[bytes]
    filename: Optional[str]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def route_url(state: AppState) -> AppState:
    url = state.get("url", "")
    if state.get("upload_content_type"):
        return {**state, "content_type": "upload", "source_type": "upload"}
    if "youtube.com" in url or "youtu.be" in url:
        return {**state, "content_type": "youtube", "source_type": "youtube"}
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
        if settings.YOUTUBE_COOKIES:
            cookie_file = f"cookies_{video_id}.txt"
            with open(cookie_file, "w", encoding="utf-8") as f:
                f.write(settings.YOUTUBE_COOKIES)

        output_template = f"temp_{video_id}"
        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": f"{output_template}.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file
        
        if settings.YOUTUBE_PROXY:
            ydl_opts["proxy"] = settings.YOUTUBE_PROXY

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get("ext", "m4a")
            title = info.get("title", "YouTube Video")
            filename = f"{output_template}.{ext}"

        print(f"Uploading {filename} to Gemini...")
        genai.configure(api_key=state["gemini_api_key"])
        gemini_file = genai.upload_file(path=filename)

        while gemini_file.state.name == "PROCESSING":
            print("Waiting for Gemini file processing…")
            time.sleep(2)
            gemini_file = genai.get_file(gemini_file.name)

        if os.path.exists(filename):
            os.remove(filename)

        return {**state, "audio_file_uri": gemini_file.name, "title": title}
    except Exception as audio_err:
        error_msg = str(audio_err)
        if "Sign in to confirm you’re not a bot" in error_msg:
            error_msg = ("YouTube blocked the server's IP. Please provide Netscape-formatted cookies "
                         "in the 'YOUTUBE_COOKIES' environment variable to bypass this.")
        return {**state, "error": f"Could not extract audio or transcripts: {error_msg}"}
    finally:
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)


def extract_upload(state: AppState) -> AppState:
    """Handle uploaded content: raw text, video file, or PDF/DOCX document."""
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

        elif upload_type == "video":
            if not file_bytes:
                return {**state, "error": "No video file received."}
            # Write to a temp file then upload to Gemini File API
            _, ext = os.path.splitext(filename)
            if not ext:
                ext = ".mp4"  # Default to mp4 if no extension is provided
            tmp_path = f"upload_video_{os.getpid()}{ext}"
            try:
                with open(tmp_path, "wb") as f:
                    f.write(file_bytes)
                print(f"Uploading video ({len(file_bytes) // 1024} KB) to Gemini…")
                genai.configure(api_key=state["gemini_api_key"])
                gemini_file = genai.upload_file(path=tmp_path, display_name=filename)
                while gemini_file.state.name == "PROCESSING":
                    print("Waiting for Gemini file processing…")
                    time.sleep(2)
                    gemini_file = genai.get_file(gemini_file.name)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            return {**state, "audio_file_uri": gemini_file.name, "title": filename,
                    "source_type": "video"}

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
