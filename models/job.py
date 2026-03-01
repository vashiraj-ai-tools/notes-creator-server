import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

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
    url: str
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
