from typing import Optional, List
from models.job import Job
from core.firebase import get_firestore

def get_job_collection(user_id: str):
    db = get_firestore()
    return db.collection("users").document(user_id).collection("jobs")

def create_job(user_id: str, url: str) -> Job:
    job = Job(user_id=user_id, url=url)
    ref = get_job_collection(user_id).document(job.job_id)
    ref.set(job.model_dump(mode="json"))
    return job

def get_job(user_id: str, job_id: str) -> Optional[Job]:
    ref = get_job_collection(user_id).document(job_id)
    doc = ref.get()
    if not doc.exists:
        return None
    return Job(**doc.to_dict())

def save_job(job: Job) -> None:
    ref = get_job_collection(job.user_id).document(job.job_id)
    ref.set(job.model_dump(mode="json"))

def get_jobs_for_user(user_id: str) -> List[Job]:
    docs = get_job_collection(user_id).order_by("created_at", direction="DESCENDING").stream()
    return [Job(**doc.to_dict()) for doc in docs]
