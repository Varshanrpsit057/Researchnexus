"""Stage S5+S6 orchestration entry point: seed paper -> SearchPlan ->
bounded multi-strategy discovery -> dedupe/filter -> persist a SearchRun +
its SearchCandidates with per-strategy provenance and signals (Roadmap
Phase 5).

Run by the `discover` job (app/jobs/runner.py), which hands in a
`DiscoveryProgress` through the options: every step -- search plan, seed
lookup, search, scoring, saving -- reports as it starts and ends, every
source request as it answers, every paper as it arrives, and the run is
saved with that record as its `report` (remediation Phase 8). The "one extra
citation hop" discretionary decision (Architecture §4) belongs to the final
orchestrator and is out of scope.

Where the time goes, and what bounds it (measured on real seeds, 62-64 s a
run before Phase 8): the search plan is one model call, capped at
`_PLAN_TIMEOUT_S` (the deterministic plan stands in if it runs over); the
seed lookup, which needs no plan, runs alongside it and asks OpenAlex and
Semantic Scholar at once, capped at `_RESOLVE_TIMEOUT_S`; every strategy's
requests go out together, each
strategy capped at `per_strategy_timeout_s` and keeping what it found when
stopped; candidates are embedded while the sources answer; and the run is
saved in one transaction instead of two commits per candidate.

IEEE-limitation traceability: every persisted SearchCandidate carries a
`provenance` blob -- which sources returned it, which strategies found it,
the merge `field_provenance`, its `raw_signals`, and its citation
relationship to the seed -- the discovery-side evidence trail the future
Phase 11 gap workflow needs (Architecture §9).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.candidate import DiscoveryStrategy, SearchPlan, SearchRun
from app.domain.user import User
from app.external.http import ExternalHttpClient, ResponseCache
from app.external.keys import source_headers
from app.llm.session import resolve_llm_session
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.faiss_store import VectorIndex
from app.security.key_vault import KeyVaultDecryptionError, KeyVaultMisconfigured
from app.services.discovery.base import DiscoveryFilters, SeedView, StrategyContext
from app.services.discovery.budget import DiscoveryBudget
from app.services.discovery.citation import CitationStrategy
from app.services.discovery.keyword import KeywordStrategy, QueryExpansionStrategy
from app.services.discovery.progress import DiscoveryProgress
from app.services.discovery.recommend import RecommendationStrategy
from app.services.discovery.resolve import resolve_seed
from app.services.discovery.runner import RunnerOutput, run_discovery_strategies
from app.services.discovery.semantic import SemanticChunkStrategy, pool_text
from app.services.discovery.semantic_doc import SpecterDocStrategy
from app.services.discovery.warm import EmbeddingWarmer, worth_warming
from app.services.normalize.canonical import normalize_arxiv_id, normalize_doi, title_hash
from app.services.normalize.dedupe import SeedIdentity
from app.services.search_concepts.concept_generator import (
    extract_reference_dois,
    fallback_plan,
    generate_search_plan,
)

_MVP_STRATEGIES = [
    DiscoveryStrategy.KEYWORD,
    DiscoveryStrategy.QUERY_EXPANSION,
    DiscoveryStrategy.CITATION,
    DiscoveryStrategy.RECOMMENDATION,
    DiscoveryStrategy.SEMANTIC,
    DiscoveryStrategy.SEMANTIC_DOC,
]
_RETRIEVAL = {
    DiscoveryStrategy.KEYWORD,
    DiscoveryStrategy.QUERY_EXPANSION,
    DiscoveryStrategy.CITATION,
    DiscoveryStrategy.RECOMMENDATION,
}
# Parallel requests share the hosts, so requests to each are spaced to stay
# under their rate limits: Semantic Scholar allows about one a second (keyed
# or not); OpenAlex answers 429 to quick bursts; arXiv asks for three seconds
# between requests -- which bounds the search step anyway; Europe PMC is
# simply not flooded. (OpenAlex's other 429 -- its keyless daily budget spent
# -- asks for a wait of minutes: not retried, see _MAX_RETRY_WAIT_S.)
_S2_HOST = "api.semanticscholar.org"
_HOST_MIN_INTERVAL_S = {
    _S2_HOST: 1.05,
    "api.openalex.org": 0.15,
    "export.arxiv.org": 3.0,
    "www.ebi.ac.uk": 0.1,
    "api.crossref.org": 0.1,
    "dblp.org": 1.0,  # DBLP asks for a gentle pace
    "api.core.ac.uk": 1.0,  # CORE's keyless quota is small
}
# Discovery runs on a deadline: a source that is slow or asks for a long
# back-off is dropped for this run (the others cover it), never waited out --
# a 5xx asking for more than _MAX_RETRY_WAIT_S is not retried at all.
_EXTERNAL_TIMEOUT_CAP_S = 12.0
_EXTERNAL_RETRIES_CAP = 1
_MAX_RETRY_WAIT_S = 5.0
_PLAN_TIMEOUT_S = 20.0
_RESOLVE_TIMEOUT_S = 15.0
# answers shared by every run in this process for the cache's lifetime: a run
# started again soon after asks again only where a source failed
_RESPONSES = ResponseCache()


class SeedPaperNotFound(Exception):
    pass


class ProfileRequired(Exception):
    """Discovery needs the seed's ResearchProfile (call `analyze` first) --
    API spec §4 precondition."""


@dataclass
class DiscoveryOptions:
    strategies: list[DiscoveryStrategy] | None = None
    max_results_per_strategy: int = 25
    min_year: int | None = None
    max_year: int | None = None
    require_abstract: bool = False
    deadline_s: float = 90.0
    max_total_candidates: int = 200
    # resolution, citations, recommendations and four keyword sources
    max_external_calls: int = 80
    per_strategy_timeout_s: float = 30.0
    http: ExternalHttpClient | None = None
    chunk_embedder: EmbeddingProvider | None = None
    doc_embedder: EmbeddingProvider | None = None
    corpus_index: VectorIndex | None = None
    corpus_records: dict | None = None
    # told what the run is doing as it happens; its record is saved as the run's report
    progress: DiscoveryProgress | None = None


@dataclass
class DiscoveryResult:
    run_id: str
    status: str
    strategies_succeeded: list[str]
    strategies_failed: list[str]
    count_raw: int
    count_after_dedupe: int
    count_after_filter: int
    warnings: list[str] = field(default_factory=list)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _build_strategies(requested: list[DiscoveryStrategy], options: DiscoveryOptions) -> list[object]:
    factory = {
        DiscoveryStrategy.KEYWORD: KeywordStrategy,
        DiscoveryStrategy.QUERY_EXPANSION: QueryExpansionStrategy,
        DiscoveryStrategy.CITATION: CitationStrategy,
        DiscoveryStrategy.RECOMMENDATION: RecommendationStrategy,
        DiscoveryStrategy.SEMANTIC: lambda: SemanticChunkStrategy(
            corpus_index=options.corpus_index, corpus_records=options.corpus_records
        ),
        DiscoveryStrategy.SEMANTIC_DOC: lambda: SpecterDocStrategy(
            corpus_index=options.corpus_index, corpus_records=options.corpus_records
        ),
    }
    return [factory[s]() for s in requested if s in factory]


async def run_discovery(
    db: Session,
    *,
    seed_paper_id: str,
    current_user: User | None,
    settings: Settings,
    options: DiscoveryOptions,
) -> DiscoveryResult:
    paper = repo.get_paper(db, seed_paper_id)
    if paper is None:
        raise SeedPaperNotFound(seed_paper_id)
    profile = repo.get_profile(db, seed_paper_id)
    if profile is None:
        raise ProfileRequired(seed_paper_id)

    progress = options.progress or DiscoveryProgress()
    started_at = datetime.now(timezone.utc)
    chunks = repo.get_chunks_for_paper(db, seed_paper_id)
    # A saved key only improves the search plan; discovery never requires one,
    # so a key that can't be read (e.g. saved under an older vault secret)
    # falls back to the deterministic plan instead of failing the run.
    key_warnings: list[str] = []
    try:
        session = resolve_llm_session(db, current_user, settings) if current_user is not None else None
    except (KeyVaultDecryptionError, KeyVaultMisconfigured):
        session = None
        key_warnings.append("search_plan_fallback_key_unusable")
    reference_dois = extract_reference_dois([r.get("raw_text", "") for r in (paper.references or [])])

    embedder = options.chunk_embedder
    warmer = EmbeddingWarmer(embedder) if embedder is not None and worth_warming(embedder) else None
    if warmer is not None:
        # the seed's own texts first, while the plan and the seed lookup wait on the network
        warmer.start()
        warmer.add([c.text for c in chunks] or [paper.abstract or profile.abstract or ""])
        warmer.add([f"{paper.title}\n{paper.abstract or profile.abstract or ''}".strip()])
    try:
        http = options.http or ExternalHttpClient(
            timeout_s=min(settings.external_timeout_s, _EXTERNAL_TIMEOUT_CAP_S),
            max_retries=min(settings.external_max_retries, _EXTERNAL_RETRIES_CAP),
            backoff_base_s=settings.external_backoff_base_s,
            cache_ttl_s=settings.external_cache_ttl_s,
            host_headers=source_headers(settings),
            host_min_interval_s=_HOST_MIN_INTERVAL_S,
            max_retry_wait_s=_MAX_RETRY_WAIT_S,
            cache=_RESPONSES,
            on_request=progress.on_request,
        )
        filters = DiscoveryFilters(
            max_results_per_strategy=options.max_results_per_strategy,
            min_year=options.min_year,
            max_year=options.max_year,
            require_abstract=options.require_abstract,
        )

        def on_records(strategy: DiscoveryStrategy, records: list[Any]) -> None:
            progress.found(strategy, records)
            if warmer is not None:
                warmer.add([pool_text(r) for r in records])

        ctx = StrategyContext(
            seed=SeedView(
                paper_id=paper.id,
                title=paper.title,
                abstract=paper.abstract or profile.abstract,
                doi=paper.doi,
                arxiv_id=paper.arxiv_id,
            ),
            seed_chunks=chunks,
            plan=fallback_plan(profile, citation_anchors=reference_dois),  # replaced by the plan below
            filters=filters,
            budget=DiscoveryBudget(
                deadline_s=options.deadline_s,
                max_total_candidates=options.max_total_candidates,
                max_external_calls=options.max_external_calls,
            ),
            http=http,
            chunk_embedder=options.chunk_embedder,
            doc_embedder=options.doc_embedder,
            on_records=on_records,
            # what the search found beyond the cap is never scored: stop embedding ahead
            after_search=warmer.close if warmer is not None else None,
        )
        requested = options.strategies or list(_MVP_STRATEGIES)

        async def make_plan() -> tuple[SearchPlan, list[str]]:
            progress.begin("plan", limit_s=_PLAN_TIMEOUT_S if session is not None else None)
            try:
                plan, warnings = await asyncio.wait_for(
                    generate_search_plan(profile, session=session, citation_anchors=reference_dois), timeout=_PLAN_TIMEOUT_S
                )
            except asyncio.TimeoutError:  # noqa: UP041 - py3.10: asyncio.TimeoutError is not the builtin
                plan, warnings = fallback_plan(profile, citation_anchors=reference_dois), ["search_plan_fallback_timeout"]
            progress.end("plan", note="model" if plan.generated_by == "llm" else "fallback")
            return plan, [*key_warnings, *warnings]

        async def find_seed() -> list[str]:
            """The seed's own OpenAlex / S2 records, which citations and
            recommendations start from; it needs no plan, so it runs alongside."""
            if DiscoveryStrategy.CITATION not in requested and DiscoveryStrategy.RECOMMENDATION not in requested:
                progress.skip("resolve", "not needed by the requested strategies")
                return []
            progress.begin("resolve", limit_s=_RESOLVE_TIMEOUT_S)
            try:
                warnings = await asyncio.wait_for(resolve_seed(ctx), timeout=_RESOLVE_TIMEOUT_S)
            except asyncio.TimeoutError:  # noqa: UP041 - py3.10: asyncio.TimeoutError is not the builtin
                warnings = ["resolve_timed_out"]
            outcome = _resolve_outcome(ctx, warnings)
            progress.end("resolve", state=outcome["state"], note=outcome["note"])
            return warnings

        (plan, plan_warnings), resolve_warnings = await asyncio.gather(make_plan(), find_seed())
        ctx.plan = plan
        progress.warn(*plan_warnings, *resolve_warnings)
        seed_identity = SeedIdentity(
            # the resolved DOI too, so the seed never comes back as its own result
            doi=normalize_doi(ctx.seed.doi),
            arxiv_id=normalize_arxiv_id(paper.arxiv_id),
            title_hash=title_hash(paper.title),
        )
        progress.exclude_seed(seed_identity)

        built = _build_strategies(requested, options)
        retrieval = [s for s in built if s.strategy in _RETRIEVAL]  # type: ignore[attr-defined]
        scoring = [s for s in built if s.strategy not in _RETRIEVAL]  # type: ignore[attr-defined]

        out = await run_discovery_strategies(
            ctx,
            retrieval_strategies=retrieval,  # type: ignore[arg-type]
            scoring_strategies=scoring,  # type: ignore[arg-type]
            per_strategy_timeout_s=options.per_strategy_timeout_s,
            seed_identity=seed_identity,
            filters=filters,
            progress=progress,
        )
    finally:
        if warmer is not None:
            await warmer.close()
    progress.warn(*out.warnings)

    progress.begin("save", total=len(out.candidates))
    run_id = _persist(db, seed_paper_id, current_user, requested, filters, out, started_at=started_at, progress=progress)
    progress.end("save")
    return DiscoveryResult(
        run_id=run_id,
        status=out.status,
        strategies_succeeded=[s.value for s in out.strategies_succeeded],
        strategies_failed=[s.value for s in out.strategies_failed],
        count_raw=out.count_raw,
        count_after_dedupe=out.count_after_dedupe,
        count_after_filter=out.count_after_filter,
        warnings=[*plan_warnings, *resolve_warnings, *out.warnings],
    )


def _resolve_outcome(ctx: StrategyContext, warnings: list[str]) -> dict[str, str]:
    """How the seed lookup went, in words that never call a lookup that
    couldn't be made an answer: not being on a source is an answer; a source
    that refused or didn't answer is a failure."""
    found_on = [name for name, hit in (("OpenAlex", ctx.seed.openalex_work), ("Semantic Scholar", ctx.seed.s2_paper_id)) if hit]
    unasked = [name for code, name in (("resolve_openalex_failed", "OpenAlex"), ("resolve_semantic_scholar_failed", "Semantic Scholar")) if code in warnings]
    if found_on:
        note = f"found on {' and '.join(found_on)}" + (f"; {' and '.join(unasked)} couldn't be asked" if unasked else "")
        return {"state": "done", "note": note}
    if "resolve_timed_out" in warnings:
        return {"state": "failed", "note": "the lookup ran out of time"}
    if unasked:
        asked = [n for n in ("OpenAlex", "Semantic Scholar") if n not in unasked]
        return {"state": "failed", "note": f"{' and '.join(unasked)} couldn't be asked" + (f"; not on {asked[0]}" if asked else "")}
    return {"state": "done", "note": "not found on OpenAlex or Semantic Scholar"}


def _persist(
    db: Session,
    seed_paper_id: str,
    current_user: User | None,
    requested: list[DiscoveryStrategy],
    filters: DiscoveryFilters,
    out: RunnerOutput,
    *,
    started_at: datetime,
    progress: DiscoveryProgress,
) -> str:
    """The run and its candidates, in one transaction. Candidate ids carry
    their position, so a run's candidates read back in the order discovery
    produced them (the ranking breaks ties by content, never by id)."""
    run_id = _new_id("run")
    report = progress.report()
    # the report covers the run up to its save: this transaction is the save
    # (no report exists unless it commits), and ranking and relationships come after
    steps = {k: v for k, v in report["steps"].items() if k not in ("rank", "trail")}
    steps["save"] = {**steps.get("save", {}), "state": "done"}
    report["steps"] = steps
    report["status"] = out.status
    report["strategies_timed_out"] = [s.value for s in out.strategies_timed_out]
    run = SearchRun(
        run_id=run_id,
        owner_id=current_user.id if current_user is not None else None,
        seed_paper_id=seed_paper_id,
        strategies_requested=requested,
        strategies_succeeded=out.strategies_succeeded,
        strategies_failed=out.strategies_failed,
        filters={
            "max_results_per_strategy": filters.max_results_per_strategy,
            "min_year": filters.min_year,
            "max_year": filters.max_year,
            "require_abstract": filters.require_abstract,
        },
        candidate_count_raw=out.count_raw,
        candidate_count_after_dedupe=out.count_after_dedupe,
        candidate_count_after_filter=out.count_after_filter,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        report=report,
    )
    repo.create_search_run(db, run, commit=False)

    seen_papers: set[str] = set()
    for position, mc in enumerate(out.candidates, start=1):
        paper_id = repo.upsert_discovered_paper(db, mc.normalized, commit=False)
        if paper_id in seen_papers:
            # two candidates dedupe kept apart landed on one stored paper: a run
            # lists a paper once (the first, strongest-evidenced, stays)
            continue
        seen_papers.add(paper_id)
        repo.add_search_candidate(
            db,
            candidate_id=f"cand_{run_id.removeprefix('run_')}_{position:04d}",
            run_id=run.run_id,
            paper_id=paper_id,
            discovery_methods=mc.discovery_methods,
            possible_duplicate_of=None,
            provenance={
                "sources": [s.value for s in mc.normalized.sources],
                "found_by_strategies": [s.value for s in mc.discovery_methods],
                "raw_signals": mc.raw_signals.model_dump(exclude_none=True),
                "field_provenance": [fp.model_dump() for fp in mc.normalized.field_provenance],
                "citation_relationship": mc.citation_relationship.value,
                "possible_duplicate": mc.normalized.possible_duplicate,
            },
            filter_kept=mc.filter_kept,
            filter_reasons=mc.filter_reasons,
            raw_signals=mc.raw_signals.model_dump(exclude_none=True),
            citation_relationship=mc.citation_relationship,
            citation_hops=mc.citation_hops,
            commit=False,
        )
    db.commit()
    return run.run_id
