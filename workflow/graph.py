"""
Assembles the LangGraph workflow and exposes two synchronous functions:
  - run_workflow(url, gemini_api_key)  – URL-based flow (YouTube / blog)
  - run_upload_workflow(...)           – Upload-based flow (video / text / document)
"""
from typing import Optional

from langgraph.graph import StateGraph, END

from workflow.nodes import (
    AppState,
    route_url,
    extract_blog,
    extract_youtube,
    extract_media_url,
    extract_upload,
    generate_notes,
)


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
_workflow = StateGraph(AppState)

_workflow.add_node("router", route_url)
_workflow.add_node("extract_blog", extract_blog)
_workflow.add_node("extract_youtube", extract_youtube)
_workflow.add_node("extract_media", extract_media_url)
_workflow.add_node("extract_upload", extract_upload)
_workflow.add_node("generate", generate_notes)

_workflow.set_entry_point("router")


def _determine_route(state: AppState) -> str:
    ct = state.get("content_type", "")
    if ct == "upload":
        return "extract_upload"
    if ct == "youtube":
        return "extract_youtube"
    if ct == "media":
        return "extract_media"
    return "extract_blog"


_workflow.add_conditional_edges(
    "router",
    _determine_route,
    {
        "extract_youtube": "extract_youtube",
        "extract_blog": "extract_blog",
        "extract_media": "extract_media",
        "extract_upload": "extract_upload",
    },
)
_workflow.add_edge("extract_youtube", "generate")
_workflow.add_edge("extract_blog", "generate")
_workflow.add_edge("extract_media", "generate")
_workflow.add_edge("extract_upload", "generate")
_workflow.add_edge("generate", END)

_graph = _workflow.compile()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def run_workflow(url: str, gemini_api_key: str) -> dict:
    """
    Synchronous wrapper for the URL-based flow.
    Returns: {"notes": str, "source": {"title": str, "type": str}}
          or {"error": str}
    """
    result = _graph.invoke({
        "url": url,
        "gemini_api_key": gemini_api_key,
        "upload_content_type": None,
        "file_bytes": None,
        "filename": None,
    })

    if result.get("error"):
        return {"error": result["error"]}

    return {
        "notes": result.get("notes", ""),
        "source": {
            "title": result.get("title", ""),
            "type": result.get("source_type", ""),
        },
    }


def run_upload_workflow(
    upload_type: str,
    text_content: Optional[str],
    file_bytes: Optional[bytes],
    filename: Optional[str],
    gemini_api_key: str,
) -> dict:
    """
    Synchronous wrapper for the upload-based flow.
    Returns: {"notes": str, "source": {"title": str, "type": str}}
          or {"error": str}
    """
    initial_state: dict = {
        "url": "",
        "gemini_api_key": gemini_api_key,
        "upload_content_type": upload_type,
        "file_bytes": file_bytes,
        "filename": filename,
        # Pre-populate extracted_text for the "text" upload type
        "extracted_text": text_content if upload_type == "text" else None,
    }

    result = _graph.invoke(initial_state)

    if result.get("error"):
        return {"error": result["error"]}

    return {
        "notes": result.get("notes", ""),
        "source": {
            "title": result.get("title", ""),
            "type": result.get("source_type", ""),
        },
    }
