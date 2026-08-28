from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# A single process's in-memory job table — appropriate for this app's
# current single-process deployment. Jobs live for the life of the
# process; nothing here depends on Celery, Redis, or any other external
# task infrastructure, per this phase's scope.
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def create_job(job_type: str, label: str) -> str:
    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "type": job_type,
            "label": label,
            "status": STATUS_PENDING,
            "error": None,
            "result": None,
            "created_at": now,
            "updated_at": now,
        }
    return job_id


def update_job(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(fields)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def list_jobs(job_type: str | None = None) -> list[dict]:
    with _lock:
        jobs = [dict(job) for job in _jobs.values() if job_type is None or job["type"] == job_type]
    jobs.sort(key=lambda job: job["created_at"], reverse=True)
    return jobs