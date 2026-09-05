"""GET /api/v1/jobs/{job_id} -- see docs/architecture/
ResearchNexus_API_Specification.md §7. SSE progress events and cancellation
are out of scope for Phase 2 (not required by the ingestion-only task)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import repository as repo
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/{job_id}")
def get_job(job_id: str, db: DbSession) -> dict[str, object]:
    job = repo.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "job not found"}})
    return job.model_dump(mode="json")
