"""Multi-paper comparison domain models (Data Model §7 `ComparisonSchema`;
API spec §6 `POST /workspaces/{id}/compare`; Roadmap Phase 10).

Grounding rule (Roadmap Phase 10: "every cell cites a span ... cells with
no support are `null`, not hallucinated"):
- a `ComparisonCell` with `text is None` is a *missing* value -- the paper
  does not state it, or the LLM's proposed value failed evidence
  validation. It is never a guess.
- a `ComparisonCell` with `text` set always carries a `span` into a real
  `paper_chunks` row and a `claim_id` (a persisted `Claim` with
  `artefact_kind="comparison_cell"`).
- every cell says *why* it looks the way it does (`status`): found in the
  text; not stated there; a value was proposed but no verbatim passage
  supports it (never shown); the paper had no text to read; or extraction
  failed for that paper. Cells stored before statuses existed read back as
  `found` or `unknown`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.domain.profile import SourceSpan


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchemaOrigin(str, Enum):
    DETERMINISTIC_UNION = "deterministic_union"
    LLM_SCHEMA = "llm_schema"


class ComparisonSchema(BaseModel):
    columns: list[str]
    generated_by: str = SchemaOrigin.DETERMINISTIC_UNION.value


class CellStatus(str, Enum):
    FOUND = "found"  # stated in the paper; `span` is the verbatim passage
    NOT_STATED = "not_stated"  # the paper's text was read; it does not state this
    UNSUPPORTED = "unsupported"  # a value was proposed, but no passage supports it verbatim
    NO_TEXT = "no_text"  # the paper has no text in the workspace to read
    NOT_EXTRACTED = "not_extracted"  # reading this paper failed; nothing was concluded
    UNKNOWN = "unknown"  # stored before statuses were recorded


class ComparisonCell(BaseModel):
    column: str
    text: str | None = None                     # None => missing, never invented
    span: SourceSpan | None = None
    claim_id: str | None = None
    grounding: str = "full_text"                 # "full_text" | "abstract"
    conflicting: list[str] = Field(default_factory=list)  # other verified values seen in evidence
    status: CellStatus | None = None

    @model_validator(mode="after")
    def _derive_status(self) -> ComparisonCell:
        if self.text is not None and self.span is not None:
            self.status = CellStatus.FOUND  # a value with evidence is found, whatever was passed
        elif self.status is None or self.status is CellStatus.FOUND:
            self.status = CellStatus.UNKNOWN
        return self

    @property
    def has_evidence(self) -> bool:
        return self.text is not None and self.span is not None


class ComparisonRow(BaseModel):
    paper_id: str
    cells: dict[str, ComparisonCell] = Field(default_factory=dict)


class Comparison(BaseModel):
    comparison_id: str
    workspace_id: str
    column_schema: ComparisonSchema
    paper_ids: list[str]
    rows: list[ComparisonRow] = Field(default_factory=list)
    coverage: float = 0.0
    decontext_eval: float | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    def api_dict(self) -> dict:
        """API spec shape: `schema` is the flat column list, not the object."""
        return {
            "comparison_id": self.comparison_id,
            "schema": list(self.column_schema.columns),
            "generated_by": self.column_schema.generated_by,
            "paper_ids": list(self.paper_ids),
            "rows": [
                {
                    "paper_id": r.paper_id,
                    "cells": {col: cell.model_dump(mode="json") for col, cell in r.cells.items()},
                }
                for r in self.rows
            ],
            "coverage": self.coverage,
            "decontext_eval": self.decontext_eval,
            # when it was made (UTC), so a reader can tell an old comparison from a fresh one
            "created_at": self.created_at.isoformat(),
        }
