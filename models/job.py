import uuid
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobSource(BaseModel):
    title: str
    type: str


class JobResult(BaseModel):
    notes: str
    source: JobSource


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    # URL-based jobs have `url` set; upload jobs leave it None
    url: Optional[str] = None
    # "url" for the classic flow, "upload" for file/text/doc submissions
    input_type: Literal["url", "upload"] = "url"
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    result: Optional[JobResult] = None
    error: Optional[str] = None


# ─── Request / Response shapes ────────────────────────────────────────────────

class CreateJobRequest(BaseModel):
    url: str
    gemini_api_key: Optional[str] = None


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    error: Optional[str] = None
