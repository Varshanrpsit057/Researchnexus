"""Cross-paper matrix (Architecture §1.1 "Gap: cross-paper matrix ...
Deterministic"; Roadmap Phase 11).

Rows = workspace papers, columns = the profile facets the gap rules reason
over. Each cell is a list of `MatrixEntry(value, raw, span)` pulled
verbatim from that paper's `ResearchProfile` (spans included, so every
downstream `GapEvidence` resolves to real text). No LLM. The roadmap notes
the matrix is "a graph projection" once Phase 13 lands; for the MVP it is
built straight from profiles.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.domain.profile import ResearchProfile, SourceSpan

FACETS: tuple[str, ...] = ("problem", "method", "dataset", "metric", "limitation", "future_work", "subdomain")

_FACET_ATTRS: dict[str, tuple[str, ...]] = {
    "problem": ("research_problem",),
    "method": ("methods", "models", "algorithms"),
    "dataset": ("datasets",),
    "metric": ("evaluation_metrics",),
    "limitation": ("limitations",),
    "future_work": ("future_work",),
    "subdomain": ("subdomains",),
}

_WS = re.compile(r"\s+")


def norm(value: str) -> str:
    return _WS.sub(" ", value).strip().lower().rstrip(".,;:")


class MatrixEntry(BaseModel):
    value: str            # normalised, for matching
    raw: str              # as written in the profile
    span: SourceSpan | None = None


class PaperMeta(BaseModel):
    paper_id: str
    title: str
    year: int | None = None
    abstract_only: bool = False


def _entries_for(profile: ResearchProfile, attrs: tuple[str, ...]) -> list[MatrixEntry]:
    out: list[MatrixEntry] = []
    for attr in attrs:
        field = getattr(profile, attr, None)
        if field is None:
            continue
        items = getattr(field, "items", None)
        if items is not None:  # ProfileList
            for it in items:
                if it.value.strip():
                    out.append(MatrixEntry(value=norm(it.value), raw=it.value.strip(), span=it.source_span))
        elif getattr(field, "value", "").strip():  # ProfileField
            out.append(MatrixEntry(value=norm(field.value), raw=field.value.strip(), span=field.source_span))
    return out


class GapMatrix:
    def __init__(self, papers: list[PaperMeta], cells: dict[tuple[str, str], list[MatrixEntry]]) -> None:
        self._papers = papers
        self._cells = cells
        self._by_id = {p.paper_id: p for p in papers}

    def facets(self) -> tuple[str, ...]:
        return FACETS

    def paper_ids(self) -> list[str]:
        return [p.paper_id for p in self._papers]

    def paper_meta(self, paper_id: str) -> PaperMeta | None:
        return self._by_id.get(paper_id)

    def entries(self, paper_id: str, facet: str) -> list[MatrixEntry]:
        return list(self._cells.get((paper_id, facet), []))

    def values(self, paper_id: str, facet: str) -> set[str]:
        return {e.value for e in self._cells.get((paper_id, facet), [])}

    def span_for(self, paper_id: str, facet: str, value: str) -> SourceSpan | None:
        for e in self._cells.get((paper_id, facet), []):
            if e.value == value and e.span is not None:
                return e.span
        return None

    def papers_with(self, facet: str, value: str) -> list[str]:
        v = norm(value)
        return [pid for pid in self.paper_ids() if v in self.values(pid, facet)]

    def papers_without(self, facet: str, value: str) -> list[str]:
        with_it = set(self.papers_with(facet, value))
        return [pid for pid in self.paper_ids() if pid not in with_it]

    def value_counts(self, facet: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for pid in self.paper_ids():
            for v in sorted(self.values(pid, facet)):
                out.setdefault(v, []).append(pid)
        return out

    def newest_year(self) -> int | None:
        years = [p.year for p in self._papers if p.year is not None]
        return max(years) if years else None

    def papers_with_year(self) -> dict[str, int]:
        return {p.paper_id: p.year for p in self._papers if p.year is not None}


def build_matrix(profiles_by_paper: dict[str, ResearchProfile], papers: list[PaperMeta]) -> GapMatrix:
    cells: dict[tuple[str, str], list[MatrixEntry]] = {}
    for meta in papers:
        profile = profiles_by_paper.get(meta.paper_id)
        for facet in FACETS:
            cells[(meta.paper_id, facet)] = (
                _entries_for(profile, _FACET_ATTRS[facet]) if profile is not None else []
            )
    return GapMatrix(papers, cells)
