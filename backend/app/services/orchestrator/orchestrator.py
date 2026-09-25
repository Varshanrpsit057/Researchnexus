"""`ResearchOrchestrator` (Architecture §4; Roadmap Phase 14).

`run_stage` is the one place every stage call passes through: it times the
call, applies a bounded timeout, retries a bounded number of times, and
always writes a `stage_runs` row (Data Model §13 `ToolLog`) whether the
call succeeds or fails -- "never blocks the path" (Architecture §4 actor
table) means logging failures never themselves raise; only the stage's own
exception propagates, and only after every attempt is exhausted.

A stage callable must, when invoked with no arguments, return something
awaitable -- `sync_call` adapts an ordinary blocking callable (e.g.
`run_ingestion`, `create_workspace`) into that shape. It deliberately does
**not** run the callable in a worker thread: every stage shares this
orchestrator's one `Session`, and SQLAlchemy sessions (SQLite connections
in particular) are not safe to use from a second thread. A sync stage's
timeout is therefore measured but not preemptive -- it cannot be cancelled
mid-call without either a second session or genuine parallelism, neither
of which is worth the complexity here. The async stages (profile,
discovery, ranking, trail) already yield at their own `await` points, so
`asyncio.wait_for` around them is a real, cancellable timeout.

`run_full_pipeline` is the fixed DAG itself: ingest -> profile -> discovery
(S5+S6 combined, per `services/discovery/pipeline.py`'s own docstring,
with the bounded "one extra citation hop" decision) -> ranking -> trail ->
workspace. It calls the real, already-tested Phase 1-13 pipeline functions
directly -- it does not reimplement any of their logic.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.jobs import JobStatus
from app.domain.orchestrator import BudgetDecision, StageName, StageRun
from app.domain.rag import RagAnswer
from app.domain.user import User
from app.domain.workspace import ResearchWorkspace
from app.jobs.runner import new_id
from app.llm.session import LlmSession
from app.services.citations.pipeline import CitationsBuildResult, build_citations
from app.services.directions.pipeline import DirectionBuildResult, build_directions
from app.services.discovery.pipeline import DiscoveryOptions, run_discovery
from app.services.discovery.relevance import (
    discovery_options as default_discovery_options,
)
from app.services.discovery.relevance import rank_options, relevance_embedder
from app.services.gaps.pipeline import GapBuildOptions, GapBuildResult, build_gaps
from app.services.orchestrator.budget import (
    decide_budget,
    degrade_top_k,
    estimate_cost_usd,
    should_authorise_extra_citation_hop,
)
from app.services.profile.pipeline import run_profile_extraction
from app.services.rag.pipeline import RagRequest, answer_question
from app.services.ranking.pipeline import rank_search_run
from app.services.synthesis.compare import ComparisonResult, build_comparison
from app.services.trail.pipeline import TrailOptions, build_trail
from app.services.workspace.pipeline import WorkspaceCreateRequest, create_workspace
from app.telemetry.stage_timer import StageTimer

# discovery bounds itself (a 90s deadline, per-source time caps); its stage
# limit only has to sit above that -- same value as the discover job's
DISCOVERY_STAGE_TIMEOUT_S = 150.0

T = TypeVar("T")


class OrchestratorError(Exception):
    """Base for errors the orchestrator itself raises (never a stage's own
    domain exception, which always propagates unchanged)."""


class InvalidStageInput(OrchestratorError):
    """A stage was asked to run without its prerequisite's output being in
    a runnable state (Roadmap Phase 14 test: "invalid stage inputs")."""


class BudgetBlocked(OrchestratorError):
    """`BudgetGuard` returned BLOCK -- the workspace has reached its
    `token_budget_usd` cap. The stage is never attempted; no tokens are
    spent (Architecture §4: "hard stop at cap -> notify user, offer raise")."""


def _hash_value(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8", errors="replace")).hexdigest()[:16]


@dataclass
class PipelineResult:
    workspace: ResearchWorkspace | None = None
    paper_id: str | None = None
    run_id: str | None = None
    extra_citation_hop_used: bool = False
    failed_stage: StageName | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ResearchOrchestrator:
    db: Session
    settings: Settings

    @staticmethod
    def sync_call(fn: Callable[[], T]) -> Callable[[], Awaitable[T]]:
        """Adapts a blocking callable to the awaitable-returning contract
        `run_stage` requires. See the module docstring for why this does
        not use `asyncio.to_thread`."""

        async def _call() -> T:
            return fn()

        return _call

    async def run_stage(
        self,
        stage: StageName,
        tool: str,
        fn: Callable[[], Awaitable[T]],
        *,
        owner_id: str,
        workspace_id: str | None = None,
        job_id: str | None = None,
        timeout_s: float | None = None,
        max_attempts: int = 1,
        input_for_hash: object = None,
        extract_usage: Callable[[T], tuple[int, int]] | None = None,
    ) -> T:
        attempts = max(1, min(max_attempts, self.settings.orchestrator_max_stage_attempts))
        timeout = self.settings.orchestrator_stage_timeout_s if timeout_s is None else timeout_s
        input_hash = _hash_value(input_for_hash)

        last_exc: Exception | None = None
        for _attempt in range(attempts):
            timer = StageTimer()
            try:
                with timer:
                    awaitable = fn()
                    result = await (asyncio.wait_for(awaitable, timeout=timeout) if timeout else awaitable)
            except Exception as e:  # noqa: BLE001 - always logged; re-raised once attempts are exhausted -- never BaseException, so Ctrl-C/SystemExit still propagate immediately
                last_exc = e
                self._record(
                    stage, tool, ok=False, error=str(e)[:500], latency_ms=timer.elapsed_ms or 0,
                    owner_id=owner_id, workspace_id=workspace_id, job_id=job_id,
                    input_hash=input_hash, output_hash=_hash_value(None),
                    tokens_prompt=0, tokens_completion=0, cost_usd=0.0,
                )
                continue
            tokens_prompt, tokens_completion = extract_usage(result) if extract_usage else (0, 0)
            cost_usd = estimate_cost_usd(tokens_prompt, tokens_completion, self.settings)
            if workspace_id is not None and cost_usd:
                repo.add_workspace_spend(
                    self.db, workspace_id, owner_id,
                    tokens_prompt=tokens_prompt, tokens_completion=tokens_completion, cost_usd=cost_usd,
                )
            self._record(
                stage, tool, ok=True, error=None, latency_ms=timer.elapsed_ms or 0,
                owner_id=owner_id, workspace_id=workspace_id, job_id=job_id,
                input_hash=input_hash, output_hash=_hash_value(result),
                tokens_prompt=tokens_prompt, tokens_completion=tokens_completion, cost_usd=cost_usd,
            )
            return result

        assert last_exc is not None
        raise last_exc

    def _record(
        self,
        stage: StageName,
        tool: str,
        *,
        ok: bool,
        error: str | None,
        latency_ms: int,
        owner_id: str,
        workspace_id: str | None,
        job_id: str | None,
        input_hash: str,
        output_hash: str,
        tokens_prompt: int,
        tokens_completion: int,
        cost_usd: float,
    ) -> None:
        run = StageRun(
            id=new_id("sr"),
            owner_id=owner_id,
            workspace_id=workspace_id,
            job_id=job_id,
            stage=stage,
            tool=tool,
            input_hash=input_hash,
            output_hash=output_hash,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            ok=ok,
            error=error,
        )
        repo.record_stage_run(self.db, run)

    # ------------------------------------------------------------------
    # The fixed pre-workspace DAG: ingest -> profile -> discovery -> ranking -> trail -> workspace
    # ------------------------------------------------------------------

    async def run_full_pipeline(
        self,
        *,
        owner: User,
        pdf_bytes: bytes,
        filename: str,
        workspace_title: str,
        job_id: str | None = None,
        discovery_options: DiscoveryOptions | None = None,
    ) -> PipelineResult:
        from app.services.ingest.pipeline import run_ingestion

        def _progress(stage: str) -> None:
            if job_id is not None:
                repo.update_job(self.db, job_id, status=JobStatus.RUNNING, progress={"stage": stage})

        _progress("ingest")
        try:
            ingest_result = await self.run_stage(
                StageName.INGEST, "run_ingestion",
                self.sync_call(lambda: run_ingestion(self.db, new_id("pap"), pdf_bytes, filename, self.settings)),
                owner_id=owner.id, job_id=job_id,
                input_for_hash={"filename": filename, "size": len(pdf_bytes)},
            )
        except Exception as e:  # noqa: BLE001 - a required stage failed; report and stop
            if job_id is not None:
                repo.update_job(self.db, job_id, status=JobStatus.FAILED, error=str(e))
            return PipelineResult(failed_stage=StageName.INGEST, error=str(e))

        paper = repo.get_paper(self.db, ingest_result.paper_id)
        self._require_profileable(paper, ingest_result.paper_id)
        assert paper is not None  # narrowed by _require_profileable

        _progress("profile")
        try:
            await self.run_stage(
                StageName.PROFILE, "run_profile_extraction",
                lambda: run_profile_extraction(self.db, paper, owner, self.settings),
                owner_id=owner.id, job_id=job_id, max_attempts=2,
                input_for_hash={"paper_id": paper.id},
            )
        except Exception as e:  # noqa: BLE001
            if job_id is not None:
                repo.update_job(self.db, job_id, status=JobStatus.FAILED, error=str(e))
            return PipelineResult(paper_id=paper.id, failed_stage=StageName.PROFILE, error=str(e))

        _progress("discovery")
        embedder = relevance_embedder(self.settings)
        options = discovery_options or default_discovery_options(embedder)
        try:
            discovery_result = await self.run_stage(
                StageName.DISCOVERY, "run_discovery",
                lambda: run_discovery(self.db, seed_paper_id=paper.id, current_user=None, settings=self.settings, options=options),
                owner_id=owner.id, job_id=job_id,
                input_for_hash={"seed_paper_id": paper.id, "strategies": options.strategies},
                timeout_s=DISCOVERY_STAGE_TIMEOUT_S,
            )
        except Exception as e:  # noqa: BLE001
            if job_id is not None:
                repo.update_job(self.db, job_id, status=JobStatus.FAILED, error=str(e))
            return PipelineResult(paper_id=paper.id, failed_stage=StageName.DISCOVERY, error=str(e))

        extra_hop_used = False
        if should_authorise_extra_citation_hop(discovery_result, self.settings):
            hop_options = self._extra_hop_options(options)
            hop_result = await self.run_stage(
                StageName.DISCOVERY, "run_discovery(extra_citation_hop)",
                lambda: run_discovery(self.db, seed_paper_id=paper.id, current_user=None, settings=self.settings, options=hop_options),
                owner_id=owner.id, job_id=job_id,
                input_for_hash={"seed_paper_id": paper.id, "strategies": hop_options.strategies, "extra_hop": True},
                timeout_s=DISCOVERY_STAGE_TIMEOUT_S,
            )
            if hop_result.count_after_filter >= discovery_result.count_after_filter:
                discovery_result = hop_result
                extra_hop_used = True
                repo.mark_extra_citation_hop(self.db, discovery_result.run_id)

        _progress("ranking")
        rank_result = await self.run_stage(
            StageName.RANKING, "rank_search_run",
            lambda: rank_search_run(
                self.db, run_id=discovery_result.run_id, settings=self.settings, options=rank_options(self.settings, embedder)
            ),
            owner_id=owner.id, job_id=job_id, input_for_hash={"run_id": discovery_result.run_id},
        )

        _progress("trail")
        await self.run_stage(
            StageName.TRAIL, "build_trail",
            lambda: build_trail(
                self.db, run_id=discovery_result.run_id, settings=self.settings, options=TrailOptions(embedder=embedder)
            ),
            owner_id=owner.id, job_id=job_id, input_for_hash={"run_id": discovery_result.run_id},
        )

        _progress("workspace")
        workspace = await self.run_stage(
            StageName.WORKSPACE, "create_workspace",
            self.sync_call(
                lambda: create_workspace(
                    self.db, owner=owner,
                    req=WorkspaceCreateRequest(title=workspace_title, seed_paper_id=paper.id, import_run_id=discovery_result.run_id),
                    settings=self.settings,
                )
            ),
            owner_id=owner.id, job_id=job_id, workspace_id=None,
            input_for_hash={"seed_paper_id": paper.id, "run_id": discovery_result.run_id},
        )

        if job_id is not None:
            repo.update_job(
                self.db, job_id, status=JobStatus.SUCCEEDED,
                progress={"stage": "done"}, result_ref=workspace.workspace_id,
            )

        return PipelineResult(
            workspace=workspace, paper_id=paper.id, run_id=discovery_result.run_id,
            extra_citation_hop_used=extra_hop_used,
            warnings=list(rank_result.warnings),
        )

    @staticmethod
    def _require_profileable(paper: object, paper_id: str) -> None:
        """PROFILE's precondition (Roadmap Phase 14: "invalid stage
        inputs") -- mirrors the same check `routers/papers.py::analyze_paper`
        already makes before calling `run_profile_extraction`."""
        if paper is None or not getattr(paper, "has_full_text", False):
            raise InvalidStageInput(f"paper {paper_id} has no extracted full text; cannot profile it")

    @staticmethod
    def _extra_hop_options(options: DiscoveryOptions) -> DiscoveryOptions:
        from dataclasses import replace

        from app.domain.candidate import DiscoveryStrategy
        from app.services.discovery.pipeline import _MVP_STRATEGIES

        # `options.strategies is None` means "use run_discovery's own
        # default set" -- the hop must add CITATION to that effective set,
        # never collapse it down to CITATION alone.
        strategies = list(options.strategies) if options.strategies else list(_MVP_STRATEGIES)
        if DiscoveryStrategy.CITATION not in strategies:
            strategies.append(DiscoveryStrategy.CITATION)
        return replace(
            options,
            strategies=strategies,
            max_results_per_strategy=options.max_results_per_strategy * 2,
        )

    # ------------------------------------------------------------------
    # Post-workspace stages: on-demand, user-triggered, each individually
    # wrapped for telemetry + budget -- these are the "orchestrated variants
    # of discover/gaps/directions already exposed" (Roadmap Phase 14).
    # ------------------------------------------------------------------

    async def run_rag_stage(
        self,
        *,
        workspace: ResearchWorkspace,
        request: RagRequest,
        session: LlmSession | None,
        owner_id: str,
        job_id: str | None = None,
        index: object = None,
        reranker: object = None,
        answer_fn: Callable[..., Awaitable[RagAnswer]] = answer_question,
    ) -> RagAnswer:
        """The RAG stage is the concrete example of "graceful degradation
        under budget" (Architecture §4 `BudgetGuard`): DEGRADE halves the
        retrieval `k`; BLOCK never calls `answer_question` at all -- no
        tokens are spent once a workspace has reached its cap."""
        decision = decide_budget(workspace, self.settings)
        if decision is BudgetDecision.BLOCK:
            self._record(
                StageName.RAG, "answer_question", ok=False, error="budget_blocked", latency_ms=0,
                owner_id=owner_id, workspace_id=workspace.workspace_id, job_id=job_id,
                input_hash=_hash_value({"query": request.query}), output_hash=_hash_value(None),
                tokens_prompt=0, tokens_completion=0, cost_usd=0.0,
            )
            raise BudgetBlocked(f"workspace {workspace.workspace_id} has reached its token budget")

        call_settings = self.settings
        if decision is BudgetDecision.DEGRADE:
            call_settings = self.settings.model_copy(
                update={"rag_retrieve_k": degrade_top_k(self.settings.rag_retrieve_k)}
            )

        async def _call() -> RagAnswer:
            return await answer_fn(
                db=self.db, workspace=workspace, request=request, session=session,
                settings=call_settings, index=index, reranker=reranker,
            )

        return await self.run_stage(
            StageName.RAG, "answer_question", _call,
            owner_id=owner_id, workspace_id=workspace.workspace_id, job_id=job_id,
            input_for_hash={"query": request.query, "mode": request.mode},
            extract_usage=lambda r: (r.prompt_tokens, r.completion_tokens),
        )

    async def run_gaps_stage(
        self,
        *,
        workspace: ResearchWorkspace,
        session: LlmSession | None,
        owner_id: str,
        job_id: str | None = None,
        options: GapBuildOptions | None = None,
        build_fn: Callable[..., Awaitable[GapBuildResult]] = build_gaps,
    ) -> GapBuildResult:
        resolved_options = options or GapBuildOptions()

        async def _call() -> GapBuildResult:
            return await build_fn(
                db=self.db, workspace=workspace, options=resolved_options, session=session, settings=self.settings
            )

        return await self.run_stage(
            StageName.GAPS, "build_gaps", _call,
            owner_id=owner_id, workspace_id=workspace.workspace_id, job_id=job_id,
            input_for_hash={"workspace_id": workspace.workspace_id},
        )

    async def run_directions_stage(
        self,
        *,
        workspace: ResearchWorkspace,
        gap_ids: list[str],
        session: LlmSession | None,
        owner_id: str,
        job_id: str | None = None,
        build_fn: Callable[..., Awaitable[DirectionBuildResult]] = build_directions,
    ) -> DirectionBuildResult:
        async def _call() -> DirectionBuildResult:
            return await build_fn(db=self.db, workspace=workspace, gap_ids=gap_ids, session=session, settings=self.settings)

        return await self.run_stage(
            StageName.DIRECTIONS, "build_directions", _call,
            owner_id=owner_id, workspace_id=workspace.workspace_id, job_id=job_id,
            input_for_hash={"gap_ids": sorted(gap_ids)},
            extract_usage=lambda r: (r.prompt_tokens, r.completion_tokens),
        )

    async def run_comparison_stage(
        self,
        *,
        workspace: ResearchWorkspace,
        comparison_id: str,
        paper_ids: list[str],
        column_schema: object,
        session: LlmSession | None,
        owner_id: str,
        job_id: str | None = None,
        index: object,
        build_fn: Callable[..., Awaitable[ComparisonResult]] = build_comparison,
    ) -> ComparisonResult:
        async def _call() -> ComparisonResult:
            return await build_fn(
                db=self.db, workspace=workspace, comparison_id=comparison_id, paper_ids=paper_ids,
                column_schema=column_schema, session=session, settings=self.settings, index=index,
            )

        return await self.run_stage(
            StageName.COMPARISON, "build_comparison", _call,
            owner_id=owner_id, workspace_id=workspace.workspace_id, job_id=job_id,
            input_for_hash={"paper_ids": sorted(paper_ids)},
            extract_usage=lambda r: (r.prompt_tokens, r.completion_tokens),
        )

    async def run_citations_stage(
        self,
        *,
        workspace: ResearchWorkspace,
        paper_ids: list[str] | None,
        formats: list[str],
        owner_id: str,
        job_id: str | None = None,
    ) -> CitationsBuildResult:
        return await self.run_stage(
            StageName.CITATIONS, "build_citations",
            self.sync_call(
                lambda: build_citations(self.db, workspace=workspace, paper_ids=paper_ids, formats=formats, owner_id=owner_id)
            ),
            owner_id=owner_id, workspace_id=workspace.workspace_id, job_id=job_id,
            input_for_hash={"paper_ids": paper_ids, "formats": sorted(formats)},
        )
