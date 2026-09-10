"""Citation + Claim domain models (Data Model §10; Roadmap Phase 9).

Two hard invariants from the design docs, enforced here and relied on by
every synthesis stage:

1. **The LLM never emits a reference string.** `Citation.formatted`
   (`apa` / `ieee` / `bibtex`) is built only by
   `app/services/citations/formatter.py` from resolved CSL metadata; an
   unresolved paper gets the literal string `"Not available"`, never a
   guess (OpenScholar reports 78-90 % hallucinated references for
   LLM-written bibliographies).
2. **No `Claim` reaches the user with `supporting_chunk_ids == []`.** A
   sentence with no supporting chunk is dropped or flagged in the answer
   text, but it never becomes a `Claim` -- the `field_validator` below
   rejects an empty list at construction.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

NOT_AVAILABLE = "Not available"


class ResolvedFrom(str, Enum):
    CROSSREF = "crossref"
    OPENALEX = "openalex"
    ARXIV = "arxiv"
    UNRESOLVED = "unresolved"


class ArtefactKind(str, Enum):
    ANSWER = "answer"
    SUMMARY = "summary"
    COMPARISON_CELL = "comparison_cell"
    GAP_STATEMENT = "gap_statement"
    DIRECTION = "direction"
    KEYPOINT = "keypoint"


class Citation(BaseModel):
    citation_id: str
    workspace_id: str
    paper_id: str
    csl_json: dict = Field(default_factory=dict)
    formatted: dict[str, str] = Field(default_factory=dict)
    resolved_from: str = ResolvedFrom.UNRESOLVED.value


class Claim(BaseModel):
    claim_id: str
    workspace_id: str
    artefact_kind: str
    artefact_id: str
    sentence: str
    supporting_chunk_ids: list[str]
    supporting_paper_ids: list[str] = Field(default_factory=list)
    is_supported: bool = False
    citation_precision: float | None = None
    citation_recall: float | None = None

    @field_validator("supporting_chunk_ids")
    @classmethod
    def _at_least_one_chunk(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("a Claim must cite at least one supporting chunk (Data Model §10 invariant)")
        return v
