"""Async job execution (FastAPI BackgroundTasks -- MVP; see Architecture §7,
"FastAPI BackgroundTasks (MVP) -> ARQ + Redis (research/prod)").

`ingest` (Phase 2) and `gaps` (Phase 11) run here. Each callable opens its
own DB session -- the request-scoped one is closed once the response is
sent -- and records success or failure on the `jobs` row, never crashing
the worker thread.
"""

from __future__ import annotations

import asyncio
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


def run_gaps_job(
    session_factory: sessionmaker,
    job_id: str,
    workspace_id: str,
    owner_id: str,
    gap_type_values: list[str] | None,
    min_supporting_papers: int,
    settings: Settings,
) -> None:
    """`POST /workspaces/{id}/gaps` -- runs the deterministic-first gap
    pipeline and persists `research_gaps` rows (Roadmap Phase 11)."""
    from app.domain.gap import GapType
    from app.llm.session import resolve_llm_session
    from app.services.gaps.pipeline import GapBuildOptions, build_gaps

    db = session_factory()
    try:
        repo.update_job(db, job_id, status=JobStatus.RUNNING, progress={"gaps": "running"})
        try:
            user = repo.get_user(db, owner_id)
            workspace = repo.get_workspace(db, workspace_id, owner_id)
            if user is None or workspace is None:
                repo.update_job(db, job_id, status=JobStatus.FAILED, error="workspace or user not found")
                return
            gap_types = {GapType(v) for v in gap_type_values} if gap_type_values else None
            session = resolve_llm_session(db, user, settings)
            result = asyncio.run(
                build_gaps(
                    db,
                    workspace=workspace,
                    options=GapBuildOptions(gap_types=gap_types, min_supporting_papers=min_supporting_papers),
                    session=session,
                    settings=settings,
                )
            )
        except Exception as e:  # noqa: BLE001 - record on the job, never crash the worker
            repo.update_job(db, job_id, status=JobStatus.FAILED, error=str(e))
            return
        repo.update_job(
            db,
            job_id,
            status=JobStatus.SUCCEEDED,
            progress={"gaps": "done", "count": str(result.gap_count)},
            result_ref=workspace_id,
        )
    finally:
        db.close()
