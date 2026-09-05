"""PaperChunk domain model.

Mirrors `paper_chunks` in docs/architecture/ResearchNexus_Data_Model.md §6/§13.
Every chunk retains full provenance (paper_id, section, page, char offsets)
so later phases (RAG citation grounding, and — per the IEEE-limitation
traceability note — evidence-grounded research-gap objects) can resolve a
generated claim back to an exact span. See docs/architecture/
ResearchNexus_Implementation_Architecture.md §9 "Research contribution
traceability".
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ChunkKind(str, Enum):
    BODY = "body"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    ABSTRACT = "abstract"


class PaperChunk(BaseModel):
    chunk_id: str
    paper_id: str
    workspace_id: str | None = None
    section: str | None = None
    section_order: int | None = None
    page: int | None = Field(default=None, ge=1)
    char_start: int = Field(ge=0)
    char_end: int
    kind: ChunkKind = ChunkKind.BODY
    text: str
    token_count: int = Field(ge=0)
    # Populated once a discovery/RAG-phase embedding provider has run
    # (Roadmap P5/P9) — Phase 2 only prepares the interface, see
    # app/retrieval/embeddings.py.
    embedding_ref: str | None = None

    @field_validator("char_end")
    @classmethod
    def _char_end_after_start(cls, v: int, info: object) -> int:
        char_start = getattr(info, "data", {}).get("char_start")
        if char_start is not None and v <= char_start:
            raise ValueError("char_end must be greater than char_start")
        return v

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("chunk text must not be blank")
        return v
