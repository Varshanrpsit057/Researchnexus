"""SQLAlchemy ORM models for Phases 1-14.

Mirrors the `users`, `api_keys`, `papers`, `paper_chunks`, `jobs`,
`research_profiles`, `search_runs`, `search_candidates`, `ranked_papers`,
`paper_relationships`, `workspaces`, `workspace_papers`, `chat_sessions`,
`chat_messages`, `citations`, `claims`, `comparisons`,
`research_gaps`, `research_directions`, `stage_runs` and `llm_calls` tables in
docs/architecture/ResearchNexus_Data_Model.md §13. Other columns from that
spec belong to later phases and are added when those phases need them, not
speculatively here.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UserORM(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("auth_provider", "auth_subject", name="ux_users_auth_identity"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    auth_provider: Mapped[str] = mapped_column(String(32), default="local")
    auth_subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # the provider every LLM stage uses when its key works (API spec §2 `default_provider`)
    default_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ApiKeyORM(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("owner_id", "provider", name="ux_api_keys_owner_provider"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    key_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_last4: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PaperORM(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doi: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_hash: Mapped[str] = mapped_column(String(64), index=True)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(255), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_full_text: Mapped[bool] = mapped_column(Boolean, default=False)
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="upload")
    sections: Mapped[list[dict]] = mapped_column(JSON, default=list)
    tables: Mapped[list[dict]] = mapped_column(JSON, default=list)
    references: Mapped[list[dict]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PaperChunkORM(Base):
    __tablename__ = "paper_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), default="body")
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class JobORM(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    result_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ResearchProfileORM(Base):
    __tablename__ = "research_profiles"
    __table_args__ = (UniqueConstraint("paper_id", "workspace_id", name="ux_research_profiles_paper_workspace"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grounding: Mapped[str] = mapped_column(String(16), default="full_text")
    profile_json: Mapped[dict] = mapped_column(JSON)
    extraction_confidence: Mapped[str] = mapped_column(String(16), default="low")
    extraction_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class SearchRunORM(Base):
    __tablename__ = "search_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seed_paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id"))
    strategies_requested: Mapped[list] = mapped_column(JSON, default=list)
    strategies_succeeded: Mapped[list] = mapped_column(JSON, default=list)
    strategies_failed: Mapped[list] = mapped_column(JSON, default=list)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    extra_citation_hop_used: Mapped[bool] = mapped_column(Boolean, default=False)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    tokens_prompt: Mapped[int] = mapped_column(Integer, default=0)
    tokens_completion: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SearchCandidateORM(Base):
    __tablename__ = "search_candidates"
    __table_args__ = (UniqueConstraint("run_id", "paper_id", name="ux_search_candidates_run_paper"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("search_runs.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id"))
    discovery_methods: Mapped[list] = mapped_column(JSON, default=list)
    citation_relationship: Mapped[str] = mapped_column(String(32), default="none")
    citation_hops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_signals: Mapped[dict] = mapped_column(JSON, default=dict)
    preliminary_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    possible_duplicate_of: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filter_kept: Mapped[bool] = mapped_column(Boolean, default=True)
    filter_reasons: Mapped[list] = mapped_column(JSON, default=list)
    # Phase 4 addition (not in Data Model §13's column list): the
    # normalisation audit trail -- which sources contributed and how each
    # metadata conflict was resolved (Roadmap Phase 4: "provenance/source
    # tracking").
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class RankedPaperORM(Base):
    __tablename__ = "ranked_papers"
    __table_args__ = (
        Index("ix_ranked_run_rank", "run_id", "final_rank"),
        UniqueConstraint("run_id", "paper_id", name="ux_ranked_run_paper"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("search_runs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(64))
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id"))
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    weights_version: Mapped[str] = mapped_column(String(32))
    fused_score: Mapped[float] = mapped_column(Float)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_rank: Mapped[int] = mapped_column(Integer)
    band: Mapped[str] = mapped_column(String(16))
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)


class PaperRelationshipORM(Base):
    """One typed trail edge. The trail pipeline writes one *primary* row per
    (run, source, target, type); the first workspace to import the run owns
    those rows, and every later workspace importing the same run gets its
    own copy (`copied_from` = the primary's id), so each workspace keeps its
    own connections and review decisions (migration 0014)."""

    __tablename__ = "paper_relationships"
    __table_args__ = (
        # at most one row per connection per workspace ...
        UniqueConstraint(
            "run_id", "source_paper_id", "target_paper_id", "relationship_type", "workspace_id",
            name="ux_paper_rel_run_src_tgt_type_ws",
        ),
        # ... and exactly one primary per connection per run
        Index(
            "ux_paper_rel_primary",
            "run_id", "source_paper_id", "target_paper_id", "relationship_type",
            unique=True,
            sqlite_where=text("copied_from IS NULL"),
            postgresql_where=text("copied_from IS NULL"),
        ),
        Index("ix_paper_relationships_workspace", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("search_runs.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # wired in Phase 8
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # a workspace's own copy of a run's primary edge; NULL on primaries
    copied_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id"))
    target_paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id"))
    relationship_type: Mapped[str] = mapped_column(String(32))
    detection_method: Mapped[str] = mapped_column(String(32))
    rule_fired: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    supporting_references: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(16))
    confidence_basis: Mapped[dict] = mapped_column(JSON, default=dict)
    user_state: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WorkspaceORM(Base):
    """Data Model §13 `workspaces`. `owner_id` is the tenant key -- every
    read in app/db/repository.py filters by it. `source_run_id` records the
    discovery run the workspace imported from (nullable; SET NULL if the run
    is deleted) so the Phase 7 `paper_relationships` rows can be resolved
    for `GET /workspaces/{id}/trail`."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    seed_paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id"))
    seed_profile_id: Mapped[str] = mapped_column(String(64))
    source_run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("search_runs.id", ondelete="SET NULL"), nullable=True
    )
    combined_index_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    token_budget_usd: Mapped[float] = mapped_column(Float, default=5.0)
    tokens_prompt: Mapped[int] = mapped_column(Integer, default=0)
    tokens_completion: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    # ADD COLUMN in migrations 0009 / 0012 appends -> keep these last to match the migrated schema order
    comparison_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    graph_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class WorkspacePaperORM(Base):
    """Data Model §13 `workspace_papers`. PK `(workspace_id, paper_id)` --
    a paper appears at most once per workspace. `owner_id` is denormalised
    from the parent workspace for the tenant filter (Data Model: "for
    RLS/tenant filter"). The `order` field of the domain model is stored as
    `sort_order` to avoid the reserved SQL word."""

    __tablename__ = "workspace_papers"
    __table_args__ = (Index("ix_wp_owner", "owner_id"),)

    workspace_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    added_by: Mapped[str] = mapped_column(String(16), default="manual")
    role: Mapped[str] = mapped_column(String(16), default="related")
    grounding: Mapped[str] = mapped_column(String(16), default="abstract")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    ranking_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChatSessionORM(Base):
    """Data Model §13 `chat_sessions`. One conversation thread over a
    workspace; messages cascade-delete with it."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChatMessageORM(Base):
    """Data Model §13 `chat_messages`. `citations` holds the list of
    `claims.id` grounding an assistant turn; `faithfulness` is the gate
    score (nullable for user turns / non-answerable turns)."""

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_msg_session", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    tokens_prompt: Mapped[int] = mapped_column(Integer, default=0)
    tokens_completion: Mapped[int] = mapped_column(Integer, default=0)
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answerable: Mapped[bool] = mapped_column(Boolean, default=True)
    # an assistant turn's outcome beyond its text (migration 0015)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    unsupported_dropped: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    warnings: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CitationORM(Base):
    """Data Model §13 `citations`. `formatted` is built only by
    app/services/citations/formatter.py -- never by an LLM."""

    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("workspace_id", "paper_id", name="ux_citations_workspace_paper"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey("papers.id"))
    csl_json: Mapped[dict] = mapped_column(JSON, default=dict)
    formatted: Mapped[dict] = mapped_column(JSON, default=dict)
    resolved_from: Mapped[str] = mapped_column(String(16), default="unresolved")


class ClaimORM(Base):
    """Data Model §13 `claims` -- the grounding audit trail. Invariant:
    `supporting_chunk_ids` is never empty (enforced on the domain model)."""

    __tablename__ = "claims"
    __table_args__ = (Index("ix_claims_workspace", "workspace_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    artefact_kind: Mapped[str] = mapped_column(String(24))
    artefact_id: Mapped[str] = mapped_column(String(64), index=True)
    sentence: Mapped[str] = mapped_column(Text)
    supporting_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    supporting_paper_ids: Mapped[list] = mapped_column(JSON, default=list)
    is_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    citation_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ComparisonORM(Base):
    """Phase 10 multi-paper comparison result. Not in the Data Model §13
    column list (which only records `workspaces.comparison_schema`); a
    dedicated table mirrors how Phases 6-8 each persisted their stage
    result (`ranked_papers`, `paper_relationships`, `workspaces`). Every
    populated cell also has a `claims` row (`artefact_kind=
    "comparison_cell"`, `artefact_id=comparisons.id`)."""

    __tablename__ = "comparisons"
    __table_args__ = (Index("ix_comparisons_workspace", "workspace_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_json: Mapped[dict] = mapped_column(JSON, default=dict)
    paper_ids: Mapped[list] = mapped_column(JSON, default=list)
    rows_json: Mapped[list] = mapped_column(JSON, default=list)
    coverage: Mapped[float] = mapped_column(Float, default=0.0)
    decontext_eval: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ResearchGapORM(Base):
    """Data Model §13 `research_gaps` -- the structured, evidence-grounded,
    confidence-labelled gap object (Architecture §9: the artefact the tracked
    IEEE BigData 2024 paper does not produce). `supporting_papers` always has
    >= 2 entries and every `supporting_evidence` item carries a real
    `SourceSpan` (enforced on the domain model). `confidence` is a band
    string, never a percentage."""

    __tablename__ = "research_gaps"
    __table_args__ = (Index("ix_research_gaps_workspace", "workspace_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    statement: Mapped[str] = mapped_column(Text)
    gap_type: Mapped[str] = mapped_column(String(32))
    supporting_papers: Mapped[list] = mapped_column(JSON, default=list)
    supporting_evidence: Mapped[list] = mapped_column(JSON, default=list)
    conflicting_evidence: Mapped[list] = mapped_column(JSON, default=list)
    why_unaddressed: Mapped[str] = mapped_column(Text, default="")
    affected_methods: Mapped[list] = mapped_column(JSON, default=list)
    affected_datasets: Mapped[list] = mapped_column(JSON, default=list)
    evidence_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    novelty_assessment: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    confidence_basis: Mapped[dict] = mapped_column(JSON, default=dict)
    proposed_direction: Mapped[str] = mapped_column(Text, default="")
    detection_rule: Mapped[str] = mapped_column(String(48), default="")
    self_support_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    user_state: Mapped[str] = mapped_column(String(16), default="candidate")
    generator_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ResearchDirectionORM(Base):
    """Data Model §13 `research_directions`. Every direction is tied to an
    accepted `research_gaps` row (`gap_id`, `ON DELETE CASCADE`) and
    inherits its evidence spans verbatim. `kind` is mandatory
    (`evidence_backed_inference` | `llm_hypothesis`) -- a direction is never
    presented as an established fact. `confidence_basis`, `flags` and
    `user_state` are not in the Data Model §13 column list; the Phase 12
    brief requires an explicit confidence basis and accept/reject handling,
    same deviation as Phase 11's `research_gaps.user_state`."""

    __tablename__ = "research_directions"
    __table_args__ = (Index("ix_research_directions_workspace", "workspace_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gap_id: Mapped[str] = mapped_column(String(64), ForeignKey("research_gaps.id", ondelete="CASCADE"), index=True)
    proposal: Mapped[str] = mapped_column(Text, default="")
    motivation: Mapped[str] = mapped_column(Text, default="")
    supporting_evidence: Mapped[list] = mapped_column(JSON, default=list)
    related_papers: Mapped[list] = mapped_column(JSON, default=list)
    suggested_method: Mapped[str] = mapped_column(Text, default="")
    possible_dataset: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_strategy: Mapped[str] = mapped_column(Text, default="")
    risks: Mapped[list] = mapped_column(JSON, default=list)
    kind: Mapped[str] = mapped_column(String(32))
    critique: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    confidence_basis: Mapped[dict] = mapped_column(JSON, default=dict)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    user_state: Mapped[str] = mapped_column(String(16), default="candidate")
    generator_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class StageRunORM(Base):
    """Data Model §13 `stage_runs` -- the orchestrator's append-only
    tool-call log (Roadmap Phase 14 `ToolLog`). Never blocks the path it
    observes: a failed write here is a logging bug, not a pipeline failure.
    No prompt/response bodies, no secrets -- only hashes, counts, and a
    short error string."""

    __tablename__ = "stage_runs"
    __table_args__ = (
        Index("ix_stage_runs_ws_stage", "workspace_id", "stage"),
        Index("ix_stage_runs_ts", "ts"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage: Mapped[str] = mapped_column(String(32))
    tool: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str] = mapped_column(String(64))
    tokens_prompt: Mapped[int] = mapped_column(Integer, default=0)
    tokens_completion: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LlmCallORM(Base):
    """One call to a model provider, with the provider's own token usage
    (Phase 2 of the remediation plan). Written for every call -- answered,
    failed, or part of a chat turn that was never saved -- because the
    provider bills them all; the budget reads real usage from here, never
    from an estimate. No prompts, replies or keys: counts, the model, and
    the kind of failure only. `workspace_id` has no foreign key on purpose:
    usage outlives a deleted workspace."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_owner_created", "owner_id", "created_at"),
        Index("ix_llm_calls_workspace", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"))
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
