import os
import time
from typing import TypedDict, Optional
from bs4 import BeautifulSoup
import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

# Load env variables from Next.js .env.local
# The working directory for the api server is api_server, so we go up one level
load_dotenv(dotenv_path="./.env.local")

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

class AppState(TypedDict):
    url: str
    content_type: Optional[str]
    title: Optional[str]
    extracted_text: Optional[str]
    audio_file_uri: Optional[str]  # Uploaded file name/uri in Gemini
    error: Optional[str]
    notes: Optional[str]
    source_type: Optional[str]

def route_url(state: AppState) -> AppState:
    url = state["url"]
    if "youtube.com" in url or "youtu.be" in url:
        return {**state, "content_type": "youtube", "source_type": "youtube"}
    else:
        return {**state, "content_type": "blog", "source_type": "article"}

def extract_blog(state: AppState) -> AppState:
    try:
        url = state["url"]
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()
            
        title = soup.title.string if soup.title else "Blog Post"
        text = soup.get_text(separator=' ', strip=True)
        
        if not text or len(text) < 100:
            return {**state, "error": "Not enough readable content found."}
            
        # Limit text length just in case
        return {**state, "extracted_text": text[:100000], "title": title}
    except Exception as e:
        return {**state, "error": f"Failed to extract blog: {str(e)}"}

def extract_youtube(state: AppState) -> AppState:
    url = state["url"]
    video_id = None
    
    # Extract video ID
    if "v=" in url:
        video_id = url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        video_id = url.split("youtu.be/")[1].split("?")[0]
        
    if not video_id:
        return {**state, "error": "Invalid YouTube URL"}

    title = "YouTube Video" # Best effort for now
    
    try:
        # Try attempting to get transcripts first (fastest)
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join([t['text'] for t in transcript])
        return {**state, "extracted_text": text, "title": "YouTube Video Notes"}
    except Exception as e:
        print(f"Transcript failed ({e}), falling back to audio download...")
        
        # Fallback to audio download
        try:
            output_template = f"temp_{video_id}"
            ydl_opts = {
                'format': 'm4a/bestaudio/best',
                'outtmpl': f'{output_template}.%(ext)s',
                'quiet': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                ext = info.get('ext', 'm4a')
                title = info.get('title', 'YouTube Video')
                filename = f"{output_template}.{ext}"
            
            # Upload to Gemini
            print(f"Uploading {filename} to Gemini...")
            gemini_file = genai.upload_file(path=filename)
            
            # Wait for processing if needed
            while gemini_file.state.name == "PROCESSING":
                print("Waiting for file processing...")
                time.sleep(2)
                gemini_file = genai.get_file(gemini_file.name)
                
            # Clean up local file
            if os.path.exists(filename):
                os.remove(filename)
                
            return {**state, "audio_file_uri": gemini_file.name, "title": title}
            
        except Exception as audio_e:
            return {**state, "error": f"Failed to extract audio or transcripts: {str(audio_e)}"}

def generate_notes(state: AppState) -> AppState:
    if state.get("error"):
        return state
        
    if not api_key:
        return {**state, "error": "GEMINI_API_KEY is missing in .env.local"}
        
    try:
        model = genai.GenerativeModel('gemini-3-flash-preview')
        
        prompt = f"""
        You are an expert educational assistant. Your task is to create clear, highly-structured, and easy-to-read revision notes based ONLY on the provided content.
        Source Title: {state.get('title', 'Content')}

        Format your response in Markdown using the following structure:
        1. Start with an H1 heading showing the title.
        2. Provide a 2-3 sentence **Quick Summary** of the content.
        3. Create a **Key Concepts** section using an unordered list.
        4. Break down the main topics into H2 headings. Under each H2, use bullet points, bold text, and brief paragraphs to explain the details clearly.
        5. Add a **Important Takeaways / Conclusion** section at the end.

        Make the notes concise but comprehensive enough for someone studying this topic. Do not include introductory or concluding conversational filler in your response, just the notes.
        """
        
        contents = [prompt]
        
        if state.get("extracted_text"):
            contents.append(state["extracted_text"])
        elif state.get("audio_file_uri"):
            gemini_file = genai.get_file(state["audio_file_uri"])
            contents.append(gemini_file)
            
        response = model.generate_content(contents)
        
        # Cleanup remote file if it was uploaded
        if state.get("audio_file_uri"):
            genai.delete_file(state["audio_file_uri"])
            
        return {**state, "notes": response.text}
    except Exception as e:
        return {**state, "error": f"AI Generation Failed: {str(e)}"}

# Build LangGraph
workflow = StateGraph(AppState)

workflow.add_node("router", route_url)
workflow.add_node("extract_blog", extract_blog)
workflow.add_node("extract_youtube", extract_youtube)
workflow.add_node("generate", generate_notes)

workflow.set_entry_point("router")

def determine_route(state: AppState):
    if state["content_type"] == "youtube":
        return "extract_youtube"
    return "extract_blog"

workflow.add_conditional_edges(
    "router",
    determine_route,
    {
        "extract_youtube": "extract_youtube",
        "extract_blog": "extract_blog"
    }
)

workflow.add_edge("extract_youtube", "generate")
workflow.add_edge("extract_blog", "generate")
workflow.add_edge("generate", END)

app_graph = workflow.compile()

async def generate_notes_workflow(url: str):
    result = app_graph.invoke({"url": url})
    
    if result.get("error"):
        return {"error": result["error"]}
        
    return {
        "success": True,
        "notes": result.get("notes"),
        "source": {
            "title": result.get("title", ""),
            "type": result.get("source_type", "")
        }
    }
