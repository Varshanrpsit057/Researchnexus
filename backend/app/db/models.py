"""SQLAlchemy ORM models for Phase 2.

Mirrors the `papers`, `paper_chunks` and `jobs` tables in docs/architecture/
ResearchNexus_Data_Model.md §13, scoped to what PDF ingestion needs. Other
columns from that spec (doi/openalex/s2 resolution, workspace scoping,
tenant `owner_id` on papers, etc.) belong to later phases and are added
when those phases need them, not speculatively here.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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
