"""Domain models for the seed-paper ingestion pipeline (Phase 2).

Mirrors docs/architecture/ResearchNexus_Implementation_Architecture.md §3
(S1 Upload / S2 Structure extraction) and the `papers` table in
docs/architecture/ResearchNexus_Data_Model.md §13.

These are pure Pydantic models (no I/O). Persistence mapping lives in
app/db/models.py.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class ParseConfidence(str, Enum):
    """Deterministic confidence in the structural extraction of a paper.

    See app/services/ingest/confidence.py for the scoring rule. This is
    always computed by rules, never asserted by an LLM (review §11, §18).
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Section(BaseModel):
    """One detected section of a paper (e.g. '3 Method').

    char_start/char_end are offsets into ParsedDocument.full_text.
    page_start/page_end are 1-indexed page numbers the section spans.
    """

    title: str
    order: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    is_fallback: bool = False
    """True when no real heading was detected and this is the single
    'Body' section covering the whole document (Architecture §3 S2 failure
    handling: 'section detection fails -> single body section, flag')."""

    @field_validator("char_end")
    @classmethod
    def _char_end_after_start(cls, v: int, info: object) -> int:
        char_start = getattr(info, "data", {}).get("char_start")
        if char_start is not None and v <= char_start:
            raise ValueError("char_end must be greater than char_start")
        return v

    @model_validator(mode="after")
    def _page_end_after_start(self) -> Section:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be >= page_start")
        return self


class TableBlock(BaseModel):
    """A table extracted verbatim from the PDF (Architecture §3 S2)."""

    page: int = Field(ge=1)
    raw_text: str
    caption: str | None = None
    order: int = Field(default=0, ge=0)


class RawReference(BaseModel):
    """One segmented entry from the References/Bibliography section.

    Full citation parsing (authors/year/DOI) is out of scope for Phase 2 —
    this only preserves the entry so later phases (citation edges,
    contradiction evidence) can resolve it (see the IEEE-limitation
    traceability note in the Architecture doc)."""

    order: int = Field(ge=0)
    raw_text: str


class ParsedDocument(BaseModel):
    """The full result of structural extraction for one PDF (Stage S2)."""

    full_text: str
    sections: list[Section] = Field(default_factory=list)
    tables: list[TableBlock] = Field(default_factory=list)
    references: list[RawReference] = Field(default_factory=list)
    page_count: int = Field(ge=0)
    has_text_layer: bool
    parse_confidence: ParseConfidence
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # read from the PDF itself: its own DOI, and its Abstract section's text
    doi: str | None = None
    abstract: str | None = None
