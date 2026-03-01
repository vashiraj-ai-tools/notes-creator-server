from models.job import Job

# Simple in-memory store. Replace with Redis / DB for production.
_jobs: dict[str, Job] = {}


def create_job(url: str) -> Job:
    job = Job(url=url)
    _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def save_job(job: Job) -> None:
    _jobs[job.job_id] = job
