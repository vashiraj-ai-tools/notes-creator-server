"""
Assembles the LangGraph workflow and exposes a single synchronous
`run_workflow(url)` function meant to be called from a background thread.
"""
from langgraph.graph import StateGraph, END

from workflow.nodes import AppState, route_url, extract_blog, extract_youtube, generate_notes


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
_workflow = StateGraph(AppState)

_workflow.add_node("router", route_url)
_workflow.add_node("extract_blog", extract_blog)
_workflow.add_node("extract_youtube", extract_youtube)
_workflow.add_node("generate", generate_notes)

_workflow.set_entry_point("router")


def _determine_route(state: AppState) -> str:
    return "extract_youtube" if state["content_type"] == "youtube" else "extract_blog"


_workflow.add_conditional_edges(
    "router",
    _determine_route,
    {"extract_youtube": "extract_youtube", "extract_blog": "extract_blog"},
)
_workflow.add_edge("extract_youtube", "generate")
_workflow.add_edge("extract_blog", "generate")
_workflow.add_edge("generate", END)

_graph = _workflow.compile()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def run_workflow(url: str, gemini_api_key: str) -> dict:
    """
    Synchronous wrapper around the compiled LangGraph.
    Returns a plain dict with either:
      - {"notes": str, "source": {"title": str, "type": str}}
      - {"error": str}
    """
    result = _graph.invoke({"url": url, "gemini_api_key": gemini_api_key})

    if result.get("error"):
        return {"error": result["error"]}

    return {
        "notes": result.get("notes", ""),
        "source": {
            "title": result.get("title", ""),
            "type": result.get("source_type", ""),
        },
    }
