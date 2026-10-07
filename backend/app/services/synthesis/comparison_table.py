"""The comparison as a table: the one model the Compare page draws and the
Word export writes (remediation Phase 12).

Both read this model, so the exported table is the on-screen table by
construction: the same columns (one per paper, in the comparison's order),
the same rows (one per field, in the schema's order), the same headings
(full titles, never truncated) and the same cell text. A cell reads as its
quoted value, or as the reason it is empty -- the labels the page has always
used (`frontend/src/lib/compare.ts` `CELL_COPY`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.domain.comparison import CellStatus, Comparison, ComparisonCell

PaperKind = Literal["seed", "member", "connected"]
ReadFrom = Literal["full_text", "abstract", "none"]

CORNER = "Field"

FIELD_LABEL = {
    "problem": "Research problem",
    "method": "Method",
    "dataset": "Datasets",
    "metric": "Metrics",
    "result": "Results",
    "limitation": "Limitations",
}

EMPTY_LABEL = {
    CellStatus.NOT_STATED: "Not stated",
    CellStatus.UNSUPPORTED: "Unverified",
    CellStatus.NO_TEXT: "No text to read",
    CellStatus.NOT_EXTRACTED: "Not read",
    CellStatus.UNKNOWN: "Not found",
}

# What each empty cell means (the page's legend; a document has no "compare again" button).
EMPTY_MEANING = {
    CellStatus.NOT_STATED: "The paper's text was read and does not state this.",
    CellStatus.UNSUPPORTED: "A value was proposed, but no passage in the paper states it word for word, so it isn't shown.",
    CellStatus.NO_TEXT: "When compared, this paper had no text at all: no abstract, and no full text yet.",
    CellStatus.NOT_EXTRACTED: "Reading this paper failed during the comparison. Comparing again may fix it.",
    CellStatus.UNKNOWN: "No value was found. This comparison predates the reason being recorded.",
}

READ_FROM_LABEL = {"full_text": "Full text", "abstract": "Abstract only", "none": "No text"}


# characters no document (and no screen) can show: dropped, so the page and the
# exported file read exactly the same text
_UNPRINTABLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def clean(text: str) -> str:
    return _UNPRINTABLE.sub("", text)


def field_label(field_name: str) -> str:
    return FIELD_LABEL.get(field_name, field_name[:1].upper() + field_name[1:])


def short_authors(authors: list[str]) -> str:
    """'A', 'A and B', or 'A et al.' -- as the workspace pages write them."""
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    return f"{authors[0]} et al."


@dataclass(frozen=True)
class PaperRecord:
    """What the table needs to know about a paper's own record."""

    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    publisher: str | None = None


@dataclass(frozen=True)
class TablePaper:
    paper_id: str
    title: str
    authors: str
    year: int | None
    kind: PaperKind
    read_from: ReadFrom
    in_workspace: bool
    publisher: str | None = None

    @property
    def meta(self) -> str:
        parts = [
            self.authors,
            str(self.year) if self.year is not None else "",
            self.publisher or "",
            READ_FROM_LABEL[self.read_from],
            "" if self.in_workspace else "No longer in the workspace",
        ]
        return " · ".join(p for p in parts if p)


@dataclass(frozen=True)
class TableCell:
    paper_id: str
    status: str
    text: str  # the quoted value, or the label of why the cell is empty
    note: str | None = None  # other values the same passage states

    @property
    def lines(self) -> list[str]:
        return [self.text] if self.note is None else [self.text, self.note]


@dataclass(frozen=True)
class TableRow:
    field: str
    label: str
    cells: list[TableCell]


@dataclass(frozen=True)
class ComparisonTable:
    comparison_id: str
    created_at: datetime
    papers: list[TablePaper]
    rows: list[TableRow]

    @property
    def header(self) -> list[str]:
        return [CORNER, *(p.title for p in self.papers)]

    def api_dict(self) -> dict:
        return {
            "comparison_id": self.comparison_id,
            "created_at": self.created_at.isoformat(),
            "corner": CORNER,
            "papers": [
                {
                    "paper_id": p.paper_id,
                    "title": p.title,
                    "authors": p.authors,
                    "year": p.year,
                    "publisher": p.publisher,
                    "kind": p.kind,
                    "read_from": p.read_from,
                    "in_workspace": p.in_workspace,
                    "meta": p.meta,
                }
                for p in self.papers
            ],
            "rows": [
                {
                    "field": r.field,
                    "label": r.label,
                    "cells": [
                        {"paper_id": c.paper_id, "status": c.status, "text": c.text, "note": c.note} for c in r.cells
                    ],
                }
                for r in self.rows
            ],
        }


class UnknownPapers(ValueError):
    """Papers were asked for that the comparison doesn't hold."""

    def __init__(self, paper_ids: list[str]) -> None:
        super().__init__(f"not in this comparison: {', '.join(paper_ids)}")
        self.paper_ids = paper_ids


def cell_status(cell: ComparisonCell | None) -> CellStatus:
    if cell is None:
        return CellStatus.UNKNOWN
    return cell.status or CellStatus.UNKNOWN


def _cell(paper_id: str, cell: ComparisonCell | None) -> TableCell:
    status = cell_status(cell)
    if status is CellStatus.FOUND and cell is not None and cell.text is not None:
        note = f"The same passage also says: {', '.join(clean(c) for c in cell.conflicting)}" if cell.conflicting else None
        return TableCell(paper_id=paper_id, status=status.value, text=clean(cell.text), note=note)
    return TableCell(paper_id=paper_id, status=status.value, text=EMPTY_LABEL[status])


def _read_from(cells: list[ComparisonCell]) -> ReadFrom:
    if any(c.grounding == "abstract" for c in cells):
        return "abstract"
    if cells and all(c.status is CellStatus.NO_TEXT for c in cells):
        return "none"
    return "full_text"


def build_table(
    comparison: Comparison,
    *,
    records: dict[str, PaperRecord],
    members: list[str],
    seed_paper_id: str | None,
    paper_ids: list[str] | None = None,
) -> ComparisonTable:
    """The comparison as the page shows it: `paper_ids` picks the columns
    shown (always in the comparison's own order); None shows them all."""
    if paper_ids is None:
        shown = list(comparison.paper_ids)
    else:
        unknown = [p for p in paper_ids if p not in comparison.paper_ids]
        if unknown:
            raise UnknownPapers(unknown)
        wanted = set(paper_ids)
        shown = [p for p in comparison.paper_ids if p in wanted]

    rows_by_paper = {r.paper_id: r for r in comparison.rows}
    papers: list[TablePaper] = []
    for pid in shown:
        record = records.get(pid) or PaperRecord(title=pid)
        cells = list(rows_by_paper[pid].cells.values()) if pid in rows_by_paper else []
        papers.append(
            TablePaper(
                paper_id=pid,
                title=clean(record.title),
                authors=clean(short_authors(record.authors)),
                year=record.year,
                kind="seed" if pid == seed_paper_id else "member" if pid in members else "connected",
                read_from=_read_from(cells),
                in_workspace=pid in members,
                publisher=record.publisher,
            )
        )

    rows = [
        TableRow(
            field=f,
            label=field_label(f),
            cells=[_cell(pid, rows_by_paper[pid].cells.get(f) if pid in rows_by_paper else None) for pid in shown],
        )
        for f in comparison.column_schema.columns
    ]
    return ComparisonTable(comparison_id=comparison.comparison_id, created_at=comparison.created_at, papers=papers, rows=rows)
