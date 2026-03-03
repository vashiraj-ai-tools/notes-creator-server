"""
REST endpoints for the notes-generation job queue.

POST  /api/jobs              – submit a new job (authenticated)
POST  /api/jobs/guest        – submit a job as a guest (no auth, IP-limited)
GET   /api/jobs/{job_id}     – poll job status
GET   /api/jobs/{job_id}/result – fetch completed notes
"""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path, Depends, Request

from models.job import (
    CreateJobRequest,
    CreateJobResponse,
    JobResult,
    JobStatus,
    JobStatusResponse,
)
from services.firestore_job_store import create_job, get_job
from services.notes_service import process_job
from services.rate_limiter import (
    check_user_rate_limit,
    record_user_request,
    check_guest_rate_limit,
    record_guest_request,
)
from core.dependencies import get_current_user, get_current_user_api_key, get_default_api_key, get_client_ip

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/", response_model=CreateJobResponse, status_code=202)
async def submit_job(
    request_body: CreateJobRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
) -> CreateJobResponse:
    """Create a new notes-generation job for an authenticated user."""
    uid = user["uid"]
    has_own_key = bool(user.get("gemini_api_key"))
    use_own_key = user.get("use_own_key", True)

    if has_own_key and use_own_key:
        # User has their own key and wants to use it → unlimited
        api_key = get_current_user_api_key(user)
    else:
        # Free tier – check rate limit
        rate_info = check_user_rate_limit(uid)
        if not rate_info["allowed"]:
            raise HTTPException(
                status_code=429,
                detail={
                    "message": f"Free tier limit reached ({rate_info['limit']} requests per 24 hours). Add your own API key for unlimited access.",
                    "remaining": 0,
                    "resets_at": rate_info["resets_at"],
                }
            )
        api_key = get_default_api_key()
        record_user_request(uid)

    job = create_job(user_id=uid, url=request_body.url)
    background_tasks.add_task(process_job, job, api_key)
    return CreateJobResponse(job_id=job.job_id, status=job.status)


@router.post("/guest", response_model=CreateJobResponse, status_code=202)
async def submit_guest_job(
    request_body: CreateJobRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> CreateJobResponse:
    """Create a notes-generation job for an anonymous guest (rate-limited by IP)."""
    client_ip = get_client_ip(request)

    rate_info = check_guest_rate_limit(client_ip)
    if not rate_info["allowed"]:
        raise HTTPException(
            status_code=429,
            detail={
                "message": f"Guest limit reached ({rate_info['limit']} requests per 24 hours). Log in for more free requests or add your own API key for unlimited access.",
                "remaining": 0,
                "resets_at": rate_info["resets_at"],
            }
        )

    api_key = get_default_api_key()
    record_guest_request(client_ip)

    # Use a hash of the IP as the pseudo user_id for storage
    import hashlib
    guest_user_id = f"guest_{hashlib.sha256(client_ip.encode()).hexdigest()[:16]}"

    job = create_job(user_id=guest_user_id, url=request_body.url)
    background_tasks.add_task(process_job, job, api_key)
    return CreateJobResponse(job_id=job.job_id, status=job.status)


@router.get("/guest/{job_id}", response_model=JobStatusResponse)
async def get_guest_job_status(
    job_id: Annotated[str, Path(description="The job ID returned by POST /api/jobs/guest")],
    request: Request,
) -> JobStatusResponse:
    """Return the current status of a guest job."""
    import hashlib
    client_ip = get_client_ip(request)
    guest_user_id = f"guest_{hashlib.sha256(client_ip.encode()).hexdigest()[:16]}"
    
    job = get_job(user_id=guest_user_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        error=job.error,
    )


@router.get("/guest/{job_id}/result", response_model=JobResult)
async def get_guest_job_result(
    job_id: Annotated[str, Path(description="The job ID returned by POST /api/jobs/guest")],
    request: Request,
) -> JobResult:
    """Return the generated notes for a guest job."""
    import hashlib
    client_ip = get_client_ip(request)
    guest_user_id = f"guest_{hashlib.sha256(client_ip.encode()).hexdigest()[:16]}"
    
    job = get_job(user_id=guest_user_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job.status == JobStatus.FAILED:
        raise HTTPException(status_code=422, detail=job.error or "Job failed with no details.")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not yet completed. Current status: '{job.status}'.",
        )
    return job.result


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
