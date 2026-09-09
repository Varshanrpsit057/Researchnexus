"""Stage S5+S6 orchestration entry point: seed paper -> SearchPlan ->
bounded multi-strategy discovery -> dedupe/filter -> persist a SearchRun +
its SearchCandidates with per-strategy provenance and signals (Roadmap
Phase 5).

Synchronous library call -- the async `POST /papers/{id}/discover-related`
job + SSE progress wrapper (Roadmap "APIs delivered") is deferred; the
substance (strategies, runner, persistence, provenance) is here and fully
tested. The "one extra citation hop" discretionary decision (Architecture
§4) belongs to the final orchestrator and is out of scope.

IEEE-limitation traceability: every persisted SearchCandidate carries a
`provenance` blob -- which sources returned it, which strategies found it,
the merge `field_provenance`, its `raw_signals`, and its citation
relationship to the seed -- the discovery-side evidence trail the future
Phase 11 gap workflow needs (Architecture §9).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.candidate import DiscoveryStrategy, SearchRun
from app.domain.user import User
from app.external.http import ExternalHttpClient
from app.llm.session import resolve_llm_session
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.faiss_store import VectorIndex
from app.services.discovery.base import DiscoveryFilters, SeedView, StrategyContext
from app.services.discovery.budget import DiscoveryBudget
from app.services.discovery.citation import CitationStrategy
from app.services.discovery.keyword import KeywordStrategy, QueryExpansionStrategy
from app.services.discovery.runner import RunnerOutput, run_discovery_strategies
from app.services.discovery.semantic import SemanticChunkStrategy
from app.services.discovery.semantic_doc import SpecterDocStrategy
from app.services.normalize.canonical import normalize_arxiv_id, normalize_doi, title_hash
from app.services.normalize.dedupe import SeedIdentity
from app.services.search_concepts.concept_generator import (
    extract_reference_dois,
    generate_search_plan,
)

_MVP_STRATEGIES = [
    DiscoveryStrategy.KEYWORD,
    DiscoveryStrategy.QUERY_EXPANSION,
    DiscoveryStrategy.CITATION,
    DiscoveryStrategy.SEMANTIC,
    DiscoveryStrategy.SEMANTIC_DOC,
]
_RETRIEVAL = {DiscoveryStrategy.KEYWORD, DiscoveryStrategy.QUERY_EXPANSION, DiscoveryStrategy.CITATION}


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
    max_external_calls: int = 40
    per_strategy_timeout_s: float = 30.0
    http: ExternalHttpClient | None = None
    chunk_embedder: EmbeddingProvider | None = None
    doc_embedder: EmbeddingProvider | None = None
    corpus_index: VectorIndex | None = None
    corpus_records: dict | None = None


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

    chunks = repo.get_chunks_for_paper(db, seed_paper_id)
    session = resolve_llm_session(db, current_user, settings) if current_user is not None else None
    reference_dois = extract_reference_dois([r.get("raw_text", "") for r in (paper.references or [])])
    plan, plan_warnings = await generate_search_plan(profile, session=session, citation_anchors=reference_dois)

    http = options.http or ExternalHttpClient(
        timeout_s=settings.external_timeout_s,
        max_retries=settings.external_max_retries,
        backoff_base_s=settings.external_backoff_base_s,
        cache_ttl_s=settings.external_cache_ttl_s,
    )
    filters = DiscoveryFilters(
        max_results_per_strategy=options.max_results_per_strategy,
        min_year=options.min_year,
        max_year=options.max_year,
        require_abstract=options.require_abstract,
    )
    ctx = StrategyContext(
        seed=SeedView(
            paper_id=paper.id,
            title=paper.title,
            abstract=paper.abstract or profile.abstract,
            doi=paper.doi,
            arxiv_id=paper.arxiv_id,
        ),
        seed_chunks=chunks,
        plan=plan,
        filters=filters,
        budget=DiscoveryBudget(
            deadline_s=options.deadline_s,
            max_total_candidates=options.max_total_candidates,
            max_external_calls=options.max_external_calls,
        ),
        http=http,
        chunk_embedder=options.chunk_embedder,
        doc_embedder=options.doc_embedder,
    )

    requested = options.strategies or list(_MVP_STRATEGIES)
    built = _build_strategies(requested, options)
    retrieval = [s for s in built if s.strategy in _RETRIEVAL]  # type: ignore[attr-defined]
    scoring = [s for s in built if s.strategy not in _RETRIEVAL]  # type: ignore[attr-defined]

    out = await run_discovery_strategies(
        ctx,
        retrieval_strategies=retrieval,  # type: ignore[arg-type]
        scoring_strategies=scoring,  # type: ignore[arg-type]
        per_strategy_timeout_s=options.per_strategy_timeout_s,
        seed_identity=SeedIdentity(
            doi=normalize_doi(paper.doi),
            arxiv_id=normalize_arxiv_id(paper.arxiv_id),
            title_hash=title_hash(paper.title),
        ),
        filters=filters,
    )

    run_id = _persist(db, seed_paper_id, current_user, requested, filters, out)
    return DiscoveryResult(
        run_id=run_id,
        status=out.status,
        strategies_succeeded=[s.value for s in out.strategies_succeeded],
        strategies_failed=[s.value for s in out.strategies_failed],
        count_raw=out.count_raw,
        count_after_dedupe=out.count_after_dedupe,
        count_after_filter=out.count_after_filter,
        warnings=[*plan_warnings, *out.warnings],
    )


def _persist(
    db: Session,
    seed_paper_id: str,
    current_user: User | None,
    requested: list[DiscoveryStrategy],
    filters: DiscoveryFilters,
    out: RunnerOutput,
) -> str:
    run = SearchRun(
        run_id=_new_id("run"),
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
        finished_at=datetime.now(timezone.utc),
    )
    repo.create_search_run(db, run)

    for mc in out.candidates:
        paper_id = repo.upsert_discovered_paper(db, mc.normalized)
        repo.add_search_candidate(
            db,
            candidate_id=_new_id("cand"),
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
        )
    return run.run_id
