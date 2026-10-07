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
import contextlib
import uuid
from dataclasses import replace

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.domain.jobs import JobStatus
from app.services.ingest.pipeline import run_ingestion
from app.telemetry.logging import get_logger

_log = get_logger(__name__)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


METADATA_TIMEOUT_S = 25.0


def complete_metadata(db: Session, paper_id: str, settings: Settings) -> dict[str, object]:
    """Look an uploaded paper's record up (authors, year, venue, publisher,
    DOI, and an abstract when the PDF has none). Never fails the upload: a
    lookup that times out or errors leaves the paper as the PDF had it."""
    from app.services.metadata.enrich import enrich_paper, metadata_http

    async def run() -> dict[str, object]:
        try:
            outcome = await asyncio.wait_for(enrich_paper(db, paper_id, metadata_http(settings)), METADATA_TIMEOUT_S)
        except asyncio.TimeoutError:
            return {"metadata": "timed_out"}
        return outcome.progress()

    try:
        return asyncio.run(run())
    except Exception:  # noqa: BLE001 - metadata is a bonus, never a reason to fail an upload
        db.rollback()
        return {"metadata": "failed"}


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
        progress: dict[str, object] = {"parse": "done"}
        if not result.deduplicated and settings.metadata_lookup:
            repo.update_job(db, job_id, status=JobStatus.RUNNING, progress={"parse": "done", "metadata": "running"})
            progress.update(complete_metadata(db, result.paper_id, settings))
        repo.update_job(
            db,
            job_id,
            status=JobStatus.SUCCEEDED,
            progress=progress,
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
    run also writes a `stage_runs` row.

    The job's `progress` follows the run as it happens: `stage` is
    profiling / detecting / checking / saving with `done` of `total`, then
    `done` with what happened to every candidate and paper
    (`GapBuildResult.summary`). A failed job always says why: a provider
    failure records its `error_code`/`error_kind` and a message naming the
    provider; a run past its time limit says so and that papers read so far
    are kept (each profile is saved as it finishes)."""
    from app.domain.gap import GapType
    from app.llm.client import LlmProviderError, describe_provider_error
    from app.llm.session import resolve_llm_session
    from app.llm.usage import usage_scope
    from app.services.gaps.pipeline import GapBuildOptions
    from app.services.orchestrator.orchestrator import ResearchOrchestrator

    db = session_factory()

    def fail(message: str, **progress: str) -> None:
        repo.update_job(db, job_id, status=JobStatus.FAILED, error=message, progress={"stage": "failed", **progress})

    def progress(step: dict[str, str]) -> None:
        repo.update_job(db, job_id, status=JobStatus.RUNNING, progress=step)

    try:
        repo.update_job(db, job_id, status=JobStatus.RUNNING, progress={"stage": "starting", "gaps": "running"})
        try:
            user = repo.get_user(db, owner_id)
            workspace = repo.get_workspace(db, workspace_id, owner_id)
            if user is None or workspace is None:
                fail("The workspace or its owner no longer exists.")
                return
            gap_types = {GapType(v) for v in gap_type_values} if gap_type_values else None
            session = resolve_llm_session(db, user, settings)
            orchestrator = ResearchOrchestrator(db=db, settings=settings)
            with usage_scope("gaps", workspace_id=workspace_id, job_id=job_id):
                result = asyncio.run(
                    orchestrator.run_gaps_stage(
                        workspace=workspace,
                        options=GapBuildOptions(gap_types=gap_types, min_supporting_papers=min_supporting_papers),
                        session=session,
                        owner_id=owner_id,
                        job_id=job_id,
                        on_progress=progress,
                    )
                )
        except LlmProviderError as e:
            fail(describe_provider_error(e), error_code="provider_error", error_kind=e.kind.value)
            return
        except asyncio.TimeoutError:
            minutes = round(settings.gap_run_timeout_s / 60)
            fail(
                f"The run took longer than {minutes} minutes and was stopped. Papers read so far are kept; run it again to continue.",
                error_code="timeout",
            )
            return
        except Exception as e:  # noqa: BLE001 - record on the job, never crash the worker
            _log.exception("gaps_job_failed", job_id=job_id, workspace_id=workspace_id)
            fail(str(e) or type(e).__name__, error_code="internal")
            return
        repo.update_job(db, job_id, status=JobStatus.SUCCEEDED, progress=result.summary(), result_ref=workspace_id)
    finally:
        db.close()

DISCOVERY_STAGE_TIMEOUT_S = 150.0
# how often a running discover job is heard from, and checked for cancellation
HEARTBEAT_S = 2.0
CANCEL_POLL_S = 1.0


def _discovery_failure(stage: str, exc: BaseException) -> str:
    """What the page says when a discover job fails: the step and the reason,
    never a bare exception name or an empty message."""
    from app.services.discovery.pipeline import ProfileRequired, SeedPaperNotFound

    if isinstance(exc, SeedPaperNotFound):
        return "The seed paper no longer exists."
    if isinstance(exc, ProfileRequired):
        return "The seed paper needs a research profile before discovery can run."
    if isinstance(exc, asyncio.TimeoutError):
        return f"The {stage} step took longer than {round(DISCOVERY_STAGE_TIMEOUT_S)} s and was stopped."
    detail = str(exc).strip()
    return f"The {stage} step failed: {detail}" if detail else f"The {stage} step failed ({type(exc).__name__})."


def run_discover_related_job(
    session_factory: sessionmaker,
    job_id: str,
    paper_id: str,
    owner_id: str,
    settings: Settings,
    criteria: dict[str, int] | None = None,
    preferred_publishers: list[str] | None = None,
) -> None:
    """`POST /papers/{id}/discover-related` -- runs discovery (S5+S6) ->
    ranking (S9-S10) -> trail typing (S11) for an already-analysed seed
    paper, in that fixed order, each stage logged via
    `ResearchOrchestrator.run_stage`. Browsing discovery results never
    requires a BYOK key: when the owner has a working one, the search plan
    is generated with it; otherwise discovery uses its deterministic
    fallback plan (trail's LLM-confirm stays on its fallback path either
    way). Ranking uses the local relevance model (see
    app/services/discovery/relevance.py), never an LLM.

    The job's `progress` follows the run as it happens (remediation Phase 8,
    app/services/discovery/progress.py): each step, strategy and source, the
    papers found so far, rewritten at least every `HEARTBEAT_S` so a page can
    tell a live run from one that has stopped. The owner can cancel it
    (`POST /jobs/{id}/cancel`): the run stops within `CANCEL_POLL_S` and
    saves nothing more. A failure says which step failed and why.

    `criteria` are the researcher's ranking criteria (remediation Phase 9),
    already validated by the route; none ranks with the initial weights."""
    from app.domain.orchestrator import StageName
    from app.domain.ranking import RankingCriteria
    from app.services.discovery.pipeline import run_discovery
    from app.services.discovery.progress import DiscoveryProgress
    from app.services.discovery.relevance import discovery_options, rank_options, relevance_embedder
    from app.services.orchestrator.orchestrator import ResearchOrchestrator
    from app.services.ranking.pipeline import rank_search_run
    from app.services.trail.pipeline import TrailOptions, build_trail

    db = session_factory()

    def write(snapshot: dict[str, object]) -> None:
        # progress is a report on the run, never a reason for it to fail
        try:
            repo.update_job(db, job_id, status=JobStatus.RUNNING, progress={**snapshot, "seed_paper_id": paper_id})
        except Exception:  # noqa: BLE001
            db.rollback()
            _log.exception("discover_progress_write_failed", job_id=job_id)

    def fail(message: str) -> None:
        # a failed write (e.g. saving the run) leaves the session needing a
        # rollback before anything, the failure itself included, can be written
        db.rollback()
        repo.update_job(db, job_id, status=JobStatus.FAILED, error=message, progress={**progress.snapshot(), "stage": "failed"})

    progress = DiscoveryProgress(write)

    async def pipeline() -> tuple[str, str]:
        orchestrator = ResearchOrchestrator(db=db, settings=settings)
        owner = repo.get_user(db, owner_id)
        # loaded once per process (and at server start); a first run waits for it here
        embedder = await asyncio.to_thread(relevance_embedder, settings)
        options = discovery_options(embedder)
        options.progress = progress
        stage = "discovery"
        try:
            discovery_result = await orchestrator.run_stage(
                StageName.DISCOVERY,
                "run_discovery",
                lambda: run_discovery(db, seed_paper_id=paper_id, current_user=owner, settings=settings, options=options),
                owner_id=owner_id,
                job_id=job_id,
                input_for_hash={"seed_paper_id": paper_id},
                # discovery bounds each of its own steps; this outer limit only has to sit above them
                timeout_s=DISCOVERY_STAGE_TIMEOUT_S,
            )
            stage = "ranking"
            progress.begin("rank")
            ranked = await orchestrator.run_stage(
                StageName.RANKING,
                "rank_search_run",
                lambda: rank_search_run(
                    db,
                    run_id=discovery_result.run_id,
                    settings=settings,
                    options=replace(
                        rank_options(settings, embedder, RankingCriteria(**(criteria or {})).to_weights()),
                        preferred_publishers=None if preferred_publishers is None else tuple(preferred_publishers),
                    ),
                ),
                owner_id=owner_id,
                job_id=job_id,
                input_for_hash={"run_id": discovery_result.run_id},
            )
            progress.end("rank", ranked=ranked.ranked_count, off_topic=ranked.off_topic_count)
            stage = "trail"
            progress.begin("trail")
            trail = await orchestrator.run_stage(
                StageName.TRAIL,
                "build_trail",
                lambda: build_trail(
                    db, run_id=discovery_result.run_id, settings=settings, options=TrailOptions(embedder=embedder)
                ),
                owner_id=owner_id,
                job_id=job_id,
                input_for_hash={"run_id": discovery_result.run_id},
            )
            progress.end("trail", edges=trail.edge_count)
        except Exception as exc:  # noqa: BLE001 - said on the job as this step's failure
            db.rollback()
            step = {"discovery": progress.current_step() or "search", "ranking": "rank", "trail": "trail"}[stage]
            progress.end(step, state="failed", note=_discovery_failure(stage, exc))
            raise _StageFailed(_discovery_failure(stage, exc)) from exc
        return discovery_result.run_id, discovery_result.status

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            progress.flush(force=True)

    async def cancelled() -> None:
        while True:
            await asyncio.sleep(CANCEL_POLL_S)
            check = session_factory()
            try:
                job = repo.get_job(check, job_id)
            finally:
                check.close()
            if job is None or job.status is JobStatus.CANCELLED:
                return

    async def supervise() -> tuple[str, str] | None:
        """The run, stopped the moment its owner cancels it."""
        work = asyncio.create_task(pipeline())
        beat = asyncio.create_task(heartbeat())
        watch = asyncio.create_task(cancelled())
        try:
            done, _ = await asyncio.wait({work, watch}, return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                return work.result()
            work.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await work
            return None
        finally:
            for task in (beat, watch):
                task.cancel()
            await asyncio.gather(beat, watch, return_exceptions=True)

    try:
        write(progress.snapshot())
        try:
            outcome = asyncio.run(supervise())
        except _StageFailed as e:
            _log.warning("discover_job_failed", job_id=job_id, paper_id=paper_id, error=str(e), exc_info=e.__cause__)
            fail(str(e))
            return
        except Exception as e:  # noqa: BLE001 - record on the job, never crash the worker
            _log.exception("discover_job_failed", job_id=job_id, paper_id=paper_id)
            fail(_discovery_failure("discovery", e))
            return
        if outcome is None:
            _log.info("discover_job_cancelled", job_id=job_id, paper_id=paper_id)
            return
        run_id, status = outcome
        repo.update_job(
            db, job_id,
            status=JobStatus.SUCCEEDED if status != "partial" else JobStatus.PARTIAL,
            progress={**progress.snapshot(), "stage": "done"}, result_ref=run_id,
        )
    finally:
        db.close()


class _StageFailed(Exception):
    """A discover stage failed; the message is what the page shows."""



def run_fulltext_job(
    session_factory: sessionmaker,
    job_id: str,
    workspace_id: str,
    owner_id: str,
    settings: Settings,
    force: bool = False,
) -> None:
    """Looks for the full text of a workspace's papers that only have their
    abstract (remediation Phase 7) -- run when papers join a workspace, and
    on request (`force`: ask again even where a recent answer was no). The
    job's `progress` counts papers as they finish; each paper's own outcome
    is kept on the paper."""
    from app.services.fulltext.batch import papers_to_read, retrieve_many

    db = session_factory()

    def progress(step: dict[str, str]) -> None:
        repo.update_job(db, job_id, status=JobStatus.RUNNING, progress=step)

    try:
        workspace = repo.get_workspace(db, workspace_id, owner_id)
        if workspace is None:
            repo.update_job(db, job_id, status=JobStatus.FAILED, error="The workspace no longer exists.", progress={"stage": "failed"})
            return
        counts = asyncio.run(retrieve_many(db, papers_to_read(db, workspace), settings, force=force, on_progress=progress))
        repo.update_job(
            db, job_id, status=JobStatus.SUCCEEDED, result_ref=workspace_id,
            progress={"stage": "done", **{k: str(v) for k, v in counts.items()}},
        )
    except Exception as e:  # noqa: BLE001 - record on the job, never crash the worker
        _log.exception("fulltext_job_failed", job_id=job_id, workspace_id=workspace_id)
        repo.update_job(db, job_id, status=JobStatus.FAILED, error=str(e) or type(e).__name__, progress={"stage": "failed"})
    finally:
        db.close()
