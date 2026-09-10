"""SQLAlchemy ORM models for Phases 1-7.

Mirrors the `users`, `api_keys`, `papers`, `paper_chunks`, `jobs`,
`research_profiles`, `search_runs`, `search_candidates`, `ranked_papers`
and `paper_relationships` tables in docs/architecture/
ResearchNexus_Data_Model.md §13. Other columns from that spec belong to
later phases and are added when those phases need them, not speculatively
here.
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
    __tablename__ = "paper_relationships"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "source_paper_id", "target_paper_id", "relationship_type",
            name="ux_paper_rel_run_src_tgt_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("search_runs.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # wired in Phase 8
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
