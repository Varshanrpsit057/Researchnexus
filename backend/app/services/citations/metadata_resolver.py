"""Citation metadata resolution (Architecture §1.1 "Citation metadata
resolution ... External"; Roadmap Phase 9).

MVP: build CSL-JSON from the metadata already normalised onto the `papers`
row in Phase 4 (title / authors / year / venue / doi / arxiv_id). A live
Crossref/OpenAlex/arXiv lookup for gaps is a thin future addition behind
the `external_lookup` hook -- it is not needed for the deterministic path
and would make tests non-hermetic.

`resolved_from` is a provenance label, never a quality claim:
  doi present      -> "crossref"   (DOI metadata canonically comes from there)
  arxiv_id present -> "arxiv"
  title + (authors or year) -> "openalex"
  otherwise        -> "unresolved"  (formatter emits "Not available")
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.db.models import PaperORM
from app.domain.citation import NOT_AVAILABLE, Citation, ResolvedFrom
from app.services.citations.formatter import build_formatted


@dataclass(frozen=True)
class ResolvedMetadata:
    csl_json: dict
    resolved_from: str


def _split_name(name: str) -> dict[str, str]:
    name = name.strip()
    if "," in name:  # "Family, Given Names"
        family, _, given = name.partition(",")
        return {"family": family.strip(), "given": given.strip()}
    parts = re.split(r"\s+", name)
    if len(parts) == 1:
        return {"family": parts[0], "given": ""}
    return {"family": parts[-1], "given": " ".join(parts[:-1])}


def _csl_type(paper: PaperORM) -> str:
    venue = (paper.venue or "").lower()
    if any(w in venue for w in ("conference", "proceedings", "workshop", "symposium")):
        return "paper-conference"
    if paper.arxiv_id and not paper.venue:
        return "article"
    return "article-journal" if paper.venue else "article"


def resolve_paper(paper: PaperORM) -> ResolvedMetadata:
    title = (paper.title or "").strip()
    authors = list(paper.authors or [])
    if not title:
        return ResolvedMetadata({"type": "article", "title": ""}, ResolvedFrom.UNRESOLVED.value)

    csl: dict = {"type": _csl_type(paper), "title": title}
    if authors:
        csl["author"] = [_split_name(a) for a in authors if a.strip()]
    if paper.year:
        csl["issued"] = {"date-parts": [[int(paper.year)]]}
    if paper.venue:
        csl["container-title"] = paper.venue
    if paper.doi:
        csl["DOI"] = paper.doi
    if paper.url:
        csl["URL"] = paper.url
    elif paper.arxiv_id:
        csl["URL"] = f"https://arxiv.org/abs/{paper.arxiv_id}"

    if paper.doi:
        resolved = ResolvedFrom.CROSSREF
    elif paper.arxiv_id:
        resolved = ResolvedFrom.ARXIV
    elif authors or paper.year:
        resolved = ResolvedFrom.OPENALEX
    else:
        resolved = ResolvedFrom.UNRESOLVED
    return ResolvedMetadata(csl, resolved.value)


def to_citation(workspace_id: str, paper: PaperORM, *, number: int | None = None) -> Citation:
    meta = resolve_paper(paper)
    if meta.resolved_from == ResolvedFrom.UNRESOLVED.value:
        formatted = {"apa": NOT_AVAILABLE, "ieee": NOT_AVAILABLE, "bibtex": NOT_AVAILABLE}
    else:
        formatted = build_formatted(meta.csl_json, number=number)
    return Citation(
        citation_id=f"cit_{workspace_id}_{paper.id}",
        workspace_id=workspace_id,
        paper_id=paper.id,
        csl_json=meta.csl_json,
        formatted=formatted,
        resolved_from=meta.resolved_from,
    )
