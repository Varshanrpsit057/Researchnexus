"""PaperCandidate / SearchRun domain models (Data Model §3) plus the two
intermediate shapes Phase 4 works with:

- `RawExternalRecord` -- one paper as returned by ONE source, wire format
  mapped to a common shape by that source's client (no canonicalisation);
- `NormalizedCandidate` -- post-canonicalisation, post-merge: one paper,
  best-effort identity, metadata merged across sources with each conflict
  resolved *and recorded* (`field_provenance`) so "which source said what"
  stays auditable (Roadmap Phase 4: "provenance/source tracking";
  Architecture §9 IEEE-limitation traceability -- discovered evidence needs
  the same audit trail as ingested evidence).

`PaperCandidate` and `SearchRun` are the persisted shapes (Data Model §13
`search_candidates` / `search_runs`); their discovery-bookkeeping fields
(raw_signals, citation_*, preliminary_rank, strategies_*) are populated by
the Phase 5 discovery runner, not here -- Phase 4 only fills identity +
bibliographic + provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateSource(str, Enum):
    ARXIV = "arxiv"
    OPENALEX = "openalex"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    CROSSREF = "crossref"


class DiscoveryStrategy(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    SEMANTIC_DOC = "semantic_doc"
    QUERY_EXPANSION = "query_expansion"
    CITATION = "citation"
    METHOD = "method"
    TOPIC = "topic"
    RESEARCH_QUESTION = "research_question"


class CitationRelationship(str, Enum):
    CITED_BY_SEED = "cited_by_seed"
    CITES_SEED = "cites_seed"
    CO_CITED = "co_cited"
    NONE = "none"


class RawSignalScores(BaseModel):
    semantic_score: float | None = None
    semantic_doc_score: float | None = None
    keyword_score: float | None = None
    method_score: float | None = None
    topic_score: float | None = None
    rq_score: float | None = None
    recency_score: float | None = None


class RawExternalRecord(BaseModel):
    source: CandidateSource
    source_native_id: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    venue: str | None = None
    url: str | None = None
    is_preprint: bool = False
    raw: dict = Field(default_factory=dict)


class FieldProvenance(BaseModel):
    field: str
    chosen_source: CandidateSource
    chosen_value: str
    rejected: list[str] = Field(default_factory=list)  # "<source>=<value>" of the losers


class NormalizedCandidate(BaseModel):
    title: str
    title_hash: str
    external_ids: dict[str, str] = Field(default_factory=dict)  # {"doi","arxiv","openalex","s2"}
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    venue: str | None = None
    url: str | None = None
    is_preprint: bool = False
    sources: list[CandidateSource] = Field(default_factory=list)
    field_provenance: list[FieldProvenance] = Field(default_factory=list)
    possible_duplicate: bool = False
    possible_duplicate_of_title_hash: str | None = None


class PaperCandidate(BaseModel):
    candidate_id: str
    run_id: str
    external_ids: dict[str, str] = Field(default_factory=dict)
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    venue: str | None = None
    url: str | None = None
    discovery_methods: list[DiscoveryStrategy] = Field(default_factory=list)
    citation_relationship: CitationRelationship = CitationRelationship.NONE
    citation_hops: int | None = None
    raw_signals: RawSignalScores = Field(default_factory=RawSignalScores)
    preliminary_rank: int | None = None
    possible_duplicate_of: str | None = None
    filter_kept: bool = True
    filter_reasons: list[str] = Field(default_factory=list)


class SearchPlan(BaseModel):
    """Output of Stage S5 search-concept generation (Architecture §3 S5).
    Produced by an LLM when a working BYOK key is available, otherwise by a
    deterministic fallback (keywords straight from the ResearchProfile)."""

    keyword_sets: list[list[str]] = Field(default_factory=list)
    expanded_queries: list[str] = Field(default_factory=list)
    perspective_questions: list[str] = Field(default_factory=list)
    citation_anchors: list[str] = Field(default_factory=list)  # DOIs pulled from the seed's references
    generated_by: str = "fallback"  # "llm" | "fallback"


class SearchRun(BaseModel):
    run_id: str
    owner_id: str | None = None
    workspace_id: str | None = None
    seed_paper_id: str
    strategies_requested: list[DiscoveryStrategy] = Field(default_factory=list)
    strategies_succeeded: list[DiscoveryStrategy] = Field(default_factory=list)
    strategies_failed: list[DiscoveryStrategy] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    extra_citation_hop_used: bool = False
    candidate_count_raw: int = 0
    candidate_count_after_dedupe: int = 0
    candidate_count_after_filter: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None
