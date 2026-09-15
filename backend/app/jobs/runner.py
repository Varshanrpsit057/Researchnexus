"""Async job execution (FastAPI BackgroundTasks -- MVP; see Architecture §7,
"FastAPI BackgroundTasks (MVP) -> ARQ + Redis (research/prod)").

`ingest` (Phase 2) and `gaps` (Phase 11) run here. Each callable opens its
own DB session -- the request-scoped one is closed once the response is
sent -- and records success or failure on the `jobs` row, never crashing
the worker thread. `run_discover_related_job` (Roadmap Phase 15) is the
first thing that calls the Phase 5/6/7 discovery/ranking/trail pipelines
from an HTTP-reachable path at all -- those stages were fully built and
tested but never wired to a route (each module's own docstring said so
explicitly); this job runs them through `ResearchOrchestrator.run_stage`
for the same `stage_runs` telemetry every other Phase 14 stage gets,
without changing a line of Phase 5/6/7's own logic.
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
    pipeline and persists `research_gaps` rows (Roadmap Phase 11). Routed
    through `ResearchOrchestrator.run_gaps_stage` (Roadmap Phase 14) so the
    run also writes a `stage_runs` row; same inputs, same result, same
    error handling."""
    from app.domain.gap import GapType
    from app.llm.session import resolve_llm_session
    from app.services.gaps.pipeline import GapBuildOptions
    from app.services.orchestrator.orchestrator import ResearchOrchestrator

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
            orchestrator = ResearchOrchestrator(db=db, settings=settings)
            result = asyncio.run(
                orchestrator.run_gaps_stage(
                    workspace=workspace,
                    options=GapBuildOptions(gap_types=gap_types, min_supporting_papers=min_supporting_papers),
                    session=session,
                    owner_id=owner_id,
                    job_id=job_id,
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

def run_discover_related_job(
    session_factory: sessionmaker,
    job_id: str,
    paper_id: str,
    owner_id: str,
    settings: Settings,
) -> None:
    """`POST /papers/{id}/discover-related` -- runs discovery (S5+S6) ->
    ranking (S9-S10) -> trail typing (S11) for an already-analysed seed
    paper, in that fixed order, each stage logged via
    `ResearchOrchestrator.run_stage`. No LLM session is used (discovery's
    search-plan generation and trail's LLM-confirm both degrade to their
    deterministic fallback paths already tested in Phases 5 and 7) --
    browsing discovery results never requires a BYOK key; only later
    generative steps (chat, gaps, directions) do."""
    from app.domain.orchestrator import StageName
    from app.services.discovery.pipeline import DiscoveryOptions, run_discovery
    from app.services.orchestrator.orchestrator import ResearchOrchestrator
    from app.services.ranking.pipeline import RankOptions, rank_search_run
    from app.services.trail.pipeline import TrailOptions, build_trail

    db = session_factory()
    try:
        repo.update_job(db, job_id, status=JobStatus.RUNNING, progress={"stage": "discovery"})
        orchestrator = ResearchOrchestrator(db=db, settings=settings)
        try:
            discovery_result = asyncio.run(
                orchestrator.run_stage(
                    StageName.DISCOVERY,
                    "run_discovery",
                    lambda: run_discovery(
                        db, seed_paper_id=paper_id, current_user=None, settings=settings, options=DiscoveryOptions()
                    ),
                    owner_id=owner_id,
                    job_id=job_id,
                    input_for_hash={"seed_paper_id": paper_id},
                )
            )

            repo.update_job(db, job_id, status=JobStatus.RUNNING, progress={"stage": "ranking"})
            asyncio.run(
                orchestrator.run_stage(
                    StageName.RANKING,
                    "rank_search_run",
                    lambda: rank_search_run(db, run_id=discovery_result.run_id, settings=settings, options=RankOptions()),
                    owner_id=owner_id,
                    job_id=job_id,
                    input_for_hash={"run_id": discovery_result.run_id},
                )
            )

            repo.update_job(db, job_id, status=JobStatus.RUNNING, progress={"stage": "trail"})
            asyncio.run(
                orchestrator.run_stage(
                    StageName.TRAIL,
                    "build_trail",
                    lambda: build_trail(db, run_id=discovery_result.run_id, settings=settings, options=TrailOptions()),
                    owner_id=owner_id,
                    job_id=job_id,
                    input_for_hash={"run_id": discovery_result.run_id},
                )
            )
        except Exception as e:  # noqa: BLE001 - record on the job, never crash the worker
            repo.update_job(db, job_id, status=JobStatus.FAILED, error=str(e))
            return

        status = JobStatus.SUCCEEDED if discovery_result.status != "partial" else JobStatus.PARTIAL
        repo.update_job(
            db, job_id, status=status,
            progress={"stage": "done"}, result_ref=discovery_result.run_id,
        )
    finally:
        db.close()

