"""
REST endpoints for the notes-generation job queue.

POST  /api/jobs              – submit a new URL job (authenticated)
POST  /api/jobs/guest        – submit a URL job as guest (no auth, IP-limited)
POST  /api/jobs/upload       – submit an upload job (authenticated)
POST  /api/jobs/guest/upload – submit an upload job as guest
GET   /api/jobs/{job_id}     – poll job status (authenticated)
GET   /api/jobs/{job_id}/result – fetch completed notes (authenticated)
"""
import hashlib
from typing import Annotated, Optional

from fastapi import (
    APIRouter, BackgroundTasks, HTTPException, Path, Depends, Request, UploadFile, File, Form
)

from models.job import (
    CreateJobRequest,
    CreateJobResponse,
    JobResult,
    JobStatus,
    JobStatusResponse,
)
from services.firestore_job_store import create_job, get_job
from services.notes_service import process_job, process_upload_job
from services.rate_limiter import (
    check_user_rate_limit,
    record_user_request,
    check_guest_rate_limit,
    record_guest_request,
)
from services.url_cache_service import get_cached_notes
from core.dependencies import get_current_user, get_current_user_api_key, get_default_api_key, get_client_ip

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _guest_user_id(client_ip: str) -> str:
    return f"guest_{hashlib.sha256(client_ip.encode()).hexdigest()[:16]}"


def _cached_response(url: str, cached: dict, user_id: str) -> CreateJobResponse:
    """
    Create a pre-completed Job from cached notes and return the submission response.
    The job is saved to Firestore so the normal poll → result flow works transparently.
    """
    from models.job import Job, JobResult, JobSource
    from services.firestore_job_store import save_job

    job = Job(user_id=user_id, url=url, status=JobStatus.COMPLETED)
    job.result = JobResult(
        notes=cached["notes"],
        source=JobSource(
            title=cached.get("source", {}).get("title", ""),
            type=cached.get("source", {}).get("type", ""),
        ),
    )
    save_job(job)
    return CreateJobResponse(job_id=job.job_id, status=job.status)


# ── URL-based job submission ───────────────────────────────────────────────────

@router.post("/", response_model=CreateJobResponse, status_code=202)
async def submit_job(
    request_body: CreateJobRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
) -> CreateJobResponse:
    """Create a new notes-generation job for an authenticated user."""
    uid = user["uid"]
    url = request_body.url

    # ── Cache check ──
    cached = get_cached_notes(url)
    if cached:
        print(f"[cache] HIT for authenticated user {uid}: {url}")
        return _cached_response(url, cached, uid)

    # ── Rate limiting / key selection ──
    has_own_key = bool(user.get("gemini_api_key"))
    use_own_key = user.get("use_own_key", True)

    if has_own_key and use_own_key:
        api_key = get_current_user_api_key(user)
    else:
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

    job = create_job(user_id=uid, url=url)
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
    url = request_body.url
    guest_user_id = _guest_user_id(client_ip)

    # ── Cache check ──
    cached = get_cached_notes(url)
    if cached:
        print(f"[cache] HIT for guest {client_ip}: {url}")
        return _cached_response(url, cached, guest_user_id)

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

    job = create_job(user_id=guest_user_id, url=url)
    background_tasks.add_task(process_job, job, api_key)
    return CreateJobResponse(job_id=job.job_id, status=job.status)


# ── Upload-based job submission ────────────────────────────────────────────────

@router.post("/upload", response_model=CreateJobResponse, status_code=202)
async def submit_upload_job(
    request: Request,
    background_tasks: BackgroundTasks,
    upload_type: str = Form(..., description="video | audio | text | document"),
    text_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
) -> CreateJobResponse:
    """Create a notes-generation job from an uploaded file or pasted text (authenticated)."""
    uid = user["uid"]
    _validate_upload_type(upload_type, text_content, file)

    has_own_key = bool(user.get("gemini_api_key"))
    use_own_key = user.get("use_own_key", True)

    if has_own_key and use_own_key:
        api_key = get_current_user_api_key(user)
    else:
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

    file_bytes, filename = await _read_upload(file)
    job = create_job(user_id=uid, url=None)
    job.input_type = "upload"
    background_tasks.add_task(
        process_upload_job, job, api_key, upload_type, text_content, file_bytes, filename
    )
    return CreateJobResponse(job_id=job.job_id, status=job.status)


@router.post("/guest/upload", response_model=CreateJobResponse, status_code=202)
async def submit_guest_upload_job(
    request: Request,
    background_tasks: BackgroundTasks,
    upload_type: str = Form(..., description="video | audio | text | document"),
    text_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> CreateJobResponse:
    """Create a notes-generation job from uploaded content for a guest (IP-limited)."""
    client_ip = get_client_ip(request)
    guest_user_id = _guest_user_id(client_ip)

    _validate_upload_type(upload_type, text_content, file)

    rate_info = check_guest_rate_limit(client_ip)
    if not rate_info["allowed"]:
        raise HTTPException(
            status_code=429,
            detail={
                "message": f"Guest limit reached ({rate_info['limit']} requests per 24 hours). Log in or add an API key for more access.",
                "remaining": 0,
                "resets_at": rate_info["resets_at"],
            }
        )

    api_key = get_default_api_key()
    record_guest_request(client_ip)

    file_bytes, filename = await _read_upload(file)
    job = create_job(user_id=guest_user_id, url=None)
    job.input_type = "upload"
    background_tasks.add_task(
        process_upload_job, job, api_key, upload_type, text_content, file_bytes, filename
    )
    return CreateJobResponse(job_id=job.job_id, status=job.status)


# ── Shared upload helpers ──────────────────────────────────────────────────────

def _validate_upload_type(upload_type: str, text_content, file):
    valid_types = {"video", "audio", "text", "document"}
    if upload_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"upload_type must be one of {valid_types}")
    if upload_type == "text" and not text_content:
        raise HTTPException(status_code=400, detail="text_content is required for upload_type 'text'")
    if upload_type in {"video", "audio", "document"} and file is None:
        raise HTTPException(status_code=400, detail=f"A file is required for upload_type '{upload_type}'")


async def _read_upload(file: Optional[UploadFile]):
    if file is None:
        return None, None
    file_bytes = await file.read()
    return file_bytes, file.filename


# ── Status & Result polling (authenticated) ────────────────────────────────────

@router.get("/guest/{job_id}", response_model=JobStatusResponse)
async def get_guest_job_status(
    job_id: Annotated[str, Path(description="The job ID returned by POST /api/jobs/guest")],
    request: Request,
) -> JobStatusResponse:
    """Return the current status of a guest job."""
    client_ip = get_client_ip(request)
    guest_user_id = _guest_user_id(client_ip)

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
    client_ip = get_client_ip(request)
    guest_user_id = _guest_user_id(client_ip)

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
