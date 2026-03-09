"""
Background tasks that execute notes-generation workflows for jobs.
"""
import asyncio
from typing import Optional

from models.job import Job, JobStatus, JobResult, JobSource
from services.firestore_job_store import save_job
from workflow.graph import run_workflow, run_upload_workflow
from services.url_cache_service import cache_notes


async def process_job(job: Job, gemini_api_key: str) -> None:
    """URL-based job: mark running, execute workflow in a thread, update state.
    Caches the result in Firestore on success so future identical URLs are instant.
    """
    job.status = JobStatus.RUNNING
    save_job(job)

    try:
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
            # Write to URL cache for future requests
            if job.url:
                await asyncio.to_thread(cache_notes, job.url, result)

    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = f"Unexpected error: {str(exc)}"
    finally:
        save_job(job)


async def process_upload_job(
    job: Job,
    gemini_api_key: str,
    upload_type: str,
    text_content: Optional[str],
    file_bytes: Optional[bytes],
    filename: Optional[str],
) -> None:
    """Upload-based job: process video/text/document content, generate notes."""
    job.status = JobStatus.RUNNING
    save_job(job)

    try:
        result = await asyncio.to_thread(
            run_upload_workflow,
            upload_type,
            text_content,
            file_bytes,
            filename,
            gemini_api_key,
        )

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
