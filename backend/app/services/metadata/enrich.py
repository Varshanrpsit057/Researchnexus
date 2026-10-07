"""Complete an uploaded paper's record from its source metadata
(remediation, 2026-10-02): the authors, year, venue, publisher, DOI and link
a PDF rarely carries, and the abstract when the PDF has none.

What the PDF says wins: its title and its own abstract are never replaced.
Authors are filled in when the PDF named none, or when the names it carried
(its embedded metadata, often a typesetter's or an editor's) share no
surname with the publisher's list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.external.http import ExternalHttpClient
from app.external.keys import source_headers
from app.services.metadata.lookup import PaperMetadata, find_metadata
from app.services.metadata.publishers import publisher_of


@dataclass
class EnrichOutcome:
    status: str  # "found" | "not_found" | "failed"
    matched_by: str | None = None
    sources: list[str] = field(default_factory=list)
    filled: list[str] = field(default_factory=list)

    def progress(self) -> dict[str, object]:
        return {"metadata": self.status, "matched_by": self.matched_by, "sources": self.sources, "filled": self.filled}


def _surnames(names: list[str]) -> set[str]:
    return {parts[-1] for n in names if (parts := re.findall(r"[a-z]+", n.lower()))}


def _authors_to_keep(current: list[str], found: list[str]) -> list[str]:
    if not found:
        return current
    if not current or not (_surnames(current) & _surnames(found)):
        return found
    return current


def metadata_http(settings: Settings) -> ExternalHttpClient:
    return ExternalHttpClient(
        timeout_s=12.0,
        max_retries=1,
        host_headers=source_headers(settings),
        host_min_interval_s={
            "api.openalex.org": 0.15,
            "api.crossref.org": 0.1,
            "api.semanticscholar.org": 1.05,
            "export.arxiv.org": 3.0,
        },
        max_retry_wait_s=4.0,
    )


def apply_metadata(paper: PaperORM, meta: PaperMetadata, *, doi_taken: bool = False) -> list[str]:
    """Fill what the paper lacks; returns the fields that changed. `doi_taken`:
    another paper already holds the found DOI (the same article, found by
    discovery), so this one doesn't take it."""
    filled: list[str] = []

    def put(name: str, value: object) -> None:
        if value not in (None, "", []) and getattr(paper, name) != value:
            setattr(paper, name, value)
            filled.append(name)

    authors = _authors_to_keep(list(paper.authors or []), meta.authors)
    if authors != list(paper.authors or []):
        put("authors", authors)
    if not paper.year:
        put("year", meta.year)
    if not paper.venue:
        put("venue", meta.venue)
    if not paper.doi and not doi_taken:
        put("doi", meta.doi)
    if not paper.url:
        put("url", meta.url)
    if not paper.publisher:
        put("publisher", meta.publisher or publisher_of(None, paper.doi))
    if not (paper.abstract or "").strip():
        put("abstract", meta.abstract)
    return filled


async def enrich_paper(db: Session, paper_id: str, http: ExternalHttpClient) -> EnrichOutcome:
    paper = db.get(PaperORM, paper_id)
    if paper is None:
        return EnrichOutcome(status="failed")
    try:
        meta = await find_metadata(http, doi=paper.doi, title=paper.title)
    except Exception:  # noqa: BLE001 - a lookup that fails leaves the paper as the PDF had it
        return EnrichOutcome(status="failed")
    if meta is None:
        # the DOI alone still names the publisher
        publisher = publisher_of(None, paper.doi)
        if publisher and not paper.publisher:
            paper.publisher = publisher
            db.commit()
            return EnrichOutcome(status="not_found", filled=["publisher"])
        return EnrichOutcome(status="not_found")
    holder = repo.doi_holder(db, meta.doi) if meta.doi else None
    filled = apply_metadata(paper, meta, doi_taken=holder is not None and holder != paper.id)
    if filled:
        db.commit()
    return EnrichOutcome(status="found", matched_by=meta.matched_by, sources=meta.sources, filled=filled)
