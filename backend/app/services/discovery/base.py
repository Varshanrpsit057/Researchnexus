"""Shared types for the discovery strategies and the runner (Architecture
§3 S6). A strategy takes a `StrategyContext` and returns a `StrategyResult`
-- normalised-enough `RawExternalRecord`s plus the partial `RawSignalScores`
fields *that strategy* can compute (Data Model §3: "raw_signals.* are only
populated by the strategy that can compute them"). Fusion/ranking is Phase
6, explicitly out of scope here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain.candidate import (
    CitationRelationship,
    DiscoveryStrategy,
    RawExternalRecord,
    SearchPlan,
)
from app.domain.chunk import PaperChunk
from app.external.http import ExternalError, ExternalHttpClient
from app.retrieval.embeddings import EmbeddingProvider
from app.services.discovery.budget import DiscoveryBudget
from app.services.normalize.canonical import primary_identity_key, to_normalized

# subset of RawSignalScores field names -> value in [0, 1]
PartialSignals = dict[str, float]


@dataclass
class SeedView:
    paper_id: str
    title: str
    abstract: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    # filled in by resolve_seed() before the strategies run: the seed's own
    # records on OpenAlex (raw work, with referenced/related works) and S2
    openalex_work: dict[str, Any] | None = None
    s2_paper_id: str | None = None
    s2_record: dict[str, Any] | None = None


@dataclass
class DiscoveryFilters:
    max_results_per_strategy: int = 30
    min_year: int | None = None
    max_year: int | None = None
    require_abstract: bool = False


@dataclass
class StrategyContext:
    seed: SeedView
    seed_chunks: Sequence[PaperChunk]
    plan: SearchPlan
    filters: DiscoveryFilters
    budget: DiscoveryBudget
    http: ExternalHttpClient
    chunk_embedder: EmbeddingProvider | None = None
    doc_embedder: EmbeddingProvider | None = None
    # set by the runner after the retrieval strategies finish, so scoring
    # strategies (semantic / semantic_doc) have something to score
    candidate_pool: list[RawExternalRecord] = field(default_factory=list)
    # told about each batch of records as a source returns it: the run's live
    # progress, and embedding them while other sources are still answering
    on_records: Callable[[DiscoveryStrategy, list[RawExternalRecord]], None] | None = None
    # what each running strategy has found so far; the runner reads it when a
    # strategy runs out of time, so what did arrive is kept
    so_far: dict[DiscoveryStrategy, Callable[[], StrategyResult]] = field(default_factory=dict)
    # awaited once the search is over, before scoring (the run stops embedding ahead)
    after_search: Callable[[], Awaitable[None]] | None = None


@dataclass
class StrategyResult:
    strategy: DiscoveryStrategy
    records: list[RawExternalRecord] = field(default_factory=list)
    signals: dict[str, PartialSignals] = field(default_factory=dict)  # keyed by record_key()
    citation_relationships: dict[str, CitationRelationship] = field(default_factory=dict)
    citation_hops: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


Fetch = Callable[[], Awaitable[list[RawExternalRecord]]]
# one planned request's outcome: its records, its error, or None while it is unanswered
Slot = list[RawExternalRecord] | ExternalError | None


async def fetch_all(ctx: StrategyContext, strategy: DiscoveryStrategy, fetches: Sequence[Fetch], slots: list[Slot]) -> None:
    """Send a strategy's planned requests at once -- each source still spaces
    its own (ExternalHttpClient's per-host interval) -- putting request i's
    records, or its error, in `slots[i]`. Callers read the slots back in
    order, so records come out in the order they were planned, never the
    order the sources answered in: a run's candidates, and the ranking made
    from them, don't depend on network timing. A request still unanswered
    when the strategy is stopped leaves its slot None."""

    async def one(i: int, fetch: Fetch) -> None:
        try:
            records = await fetch()
        except ExternalError as e:
            slots[i] = e
            return
        slots[i] = records
        if records and ctx.on_records is not None:
            ctx.on_records(strategy, records)

    await asyncio.gather(*(one(i, f) for i, f in enumerate(fetches)))


def unanswered(slots: Sequence[Slot]) -> int:
    return sum(1 for s in slots if s is None)


class DiscoveryStrategyRunner(Protocol):
    strategy: DiscoveryStrategy

    async def run(self, ctx: StrategyContext) -> StrategyResult: ...


def record_key(rec: RawExternalRecord) -> str:
    """The identity key a strategy tags a record's signal with; the runner
    matches it back to a merged candidate via that candidate's full
    identity_keys() set."""
    return primary_identity_key(to_normalized(rec))
