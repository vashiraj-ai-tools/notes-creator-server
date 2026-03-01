"""
Background task that executes the notes-generation workflow for a given job.
"""
import asyncio

from models.job import Job, JobStatus, JobResult, JobSource
from services.firestore_job_store import save_job
from workflow.graph import run_workflow


async def process_job(job: Job, gemini_api_key: str) -> None:
    """Mark the job running, execute the workflow in a thread, then update state."""
    job.status = JobStatus.RUNNING
    save_job(job)

    try:
        # run_workflow is synchronous (LangGraph invoke); run it off the event loop.
        result = await asyncio.to_thread(run_workflow, job.url, gemini_api_key)

        if result.get("error"):
            job.status = JobStatus.FAILED
            job.error = result["error"]
        else:
            job.status = JobStatus.COMPLETED
            job.result = JobResult(
                notes=result["notes"],
                source=JobSource(
                    title=result["source"].get("title", ""),
                    type=result["source"].get("type", ""),
                ),
            )
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = f"Unexpected error: {str(exc)}"
    finally:
        save_job(job)
