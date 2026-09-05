"""Async job execution (FastAPI BackgroundTasks -- MVP; see Architecture §7,
"FastAPI BackgroundTasks (MVP) -> ARQ + Redis (research/prod)"). Phase 2
only needs the `ingest` job kind."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.domain.jobs import JobStatus
from app.services.ingest.pipeline import run_ingestion


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def run_ingest_job(
    session_factory: sessionmaker,
    job_id: str,
    paper_id: str,
    pdf_bytes: bytes,
    filename: str,
    settings: Settings,
) -> None:
    """Executed by FastAPI's BackgroundTasks (a threadpool for sync
    callables) -- must open its own DB session rather than reuse the
    request-scoped one, which is closed once the response is sent."""
    db = session_factory()
    try:
        repo.update_job(db, job_id, status=JobStatus.RUNNING, progress={"parse": "running"})
        try:
            result = run_ingestion(db, paper_id, pdf_bytes, filename, settings)
        except Exception as e:  # noqa: BLE001 - surface any failure on the job, never crash silently
            repo.update_job(db, job_id, status=JobStatus.FAILED, error=str(e))
            return
        repo.update_job(
            db,
            job_id,
            status=JobStatus.SUCCEEDED,
            progress={"parse": "done"},
            result_ref=result.paper_id,
        )
    finally:
        db.close()
