"""GET /api/v1/jobs/{job_id} -- see docs/architecture/
ResearchNexus_API_Specification.md §7 -- and, since remediation Phase 8,
POST /api/v1/jobs/{job_id}/cancel for the kinds whose workers stop when
asked (discovery).

A discover job rewrites its progress every few seconds while it runs
(app/jobs/runner.py HEARTBEAT_S); one not heard from for `STALE_AFTER` has
stopped -- its worker died without saying so -- and is reported as failed
rather than left "running" for a page to wait on forever. (A server restart
is caught earlier: every job still running then is failed at startup.)"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import repository as repo
from app.db.session import get_db
from app.deps import CurrentUser
from app.domain.jobs import Job, JobKind, JobStatus

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

DbSession = Annotated[Session, Depends(get_db)]

STALE_AFTER = timedelta(seconds=60)
# kinds whose worker watches for cancellation; cancelling any other would be a promise nothing keeps
CANCELLABLE = frozenset({JobKind.DISCOVER})
_ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)


def is_stale(job: Job, now: datetime | None = None) -> bool:
    return (
        job.kind in CANCELLABLE
        and job.status in _ACTIVE
        and (now or datetime.now(timezone.utc)) - job.updated_at > STALE_AFTER
    )


def job_json(job: Job) -> dict[str, object]:
    body = job.model_dump(mode="json")
    if is_stale(job):
        body["status"] = JobStatus.FAILED.value
        body["error"] = "The run stopped responding before it finished."
        body["progress"] = {**job.progress, "stage": "interrupted"}
    return body


@router.get("/{job_id}")
def get_job(job_id: str, db: DbSession, current_user: CurrentUser) -> dict[str, object]:
    job = repo.get_job(db, job_id)
    if job is None or job.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "job not found"}})
    return job_json(job)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, db: DbSession, current_user: CurrentUser) -> dict[str, object]:
    """Stop a running job. Cancelling one that already finished changes
    nothing and returns it as it is."""
    job = repo.get_job(db, job_id)
    if job is None or job.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "job not found"}})
    if job.kind not in CANCELLABLE:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "conflict", "message": f"a {job.kind.value} job can't be cancelled"}},
        )
    cancelled = repo.cancel_job(db, job_id)
    assert cancelled is not None
    return job_json(cancelled)
