"""
REST endpoints for the notes-generation job queue.

POST  /api/jobs              – submit a new job
GET   /api/jobs/{job_id}     – poll job status
GET   /api/jobs/{job_id}/result – fetch completed notes
"""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path, Depends

from models.job import (
    CreateJobRequest,
    CreateJobResponse,
    JobResult,
    JobStatus,
    JobStatusResponse,
)
from services.firestore_job_store import create_job, get_job
from services.notes_service import process_job
from core.dependencies import get_current_user, get_current_user_api_key

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/", response_model=CreateJobResponse, status_code=202)
async def submit_job(
    request: CreateJobRequest, 
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
) -> CreateJobResponse:
    """Create a new notes-generation job and queue it for processing."""
    api_key = request.gemini_api_key
    if not api_key:
        api_key = get_current_user_api_key(user)
        
    job = create_job(user_id=user["uid"], url=request.url)
    background_tasks.add_task(process_job, job, api_key)
    return CreateJobResponse(job_id=job.job_id, status=job.status)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: Annotated[str, Path(description="The job ID returned by POST /api/jobs")],
    user: dict = Depends(get_current_user)
) -> JobStatusResponse:
    """Return the current status of a job."""
    job = get_job(user_id=user["uid"], job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        error=job.error,
    )


@router.get("/{job_id}/result", response_model=JobResult)
async def get_job_result(
    job_id: Annotated[str, Path(description="The job ID returned by POST /api/jobs")],
    user: dict = Depends(get_current_user)
) -> JobResult:
    """Return the generated notes. Only available once the job status is 'completed'."""
    job = get_job(user_id=user["uid"], job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job.status == JobStatus.FAILED:
        raise HTTPException(status_code=422, detail=job.error or "Job failed with no details.")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not yet completed. Current status: '{job.status}'.",
        )
    return job.result  # type: ignore[return-value]
