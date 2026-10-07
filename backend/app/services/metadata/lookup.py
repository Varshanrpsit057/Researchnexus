"""A paper's bibliographic record, from the sources that hold it
(remediation, 2026-10-02).

An uploaded PDF often carries no usable metadata: IEEE leaves the PDF's
author field empty, and a title page set in several columns cannot be read
into a reliable author list. The record is looked up instead -- by the DOI
printed on the paper, else by its exact title -- in several sources, so one
that is unavailable (OpenAlex's keyless daily budget runs out; Semantic
Scholar rate-limits keyless use) doesn't leave the paper without a record:

- Crossref: by DOI, else by its bibliographic search (publishers' own
  deposits: authors in their order, venue, publisher, year);
- OpenAlex: by DOI (authors, year, and often the abstract);
- Semantic Scholar's title match, and arXiv by title, for preprints.

Only a confident match is used: the DOI the paper itself prints, or a title
that is the same after normalisation. Each field comes from the first source
that has it, in the order above.
"""

from __future__ import annotations

import html
import re
from collections.abc import Awaitable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, TypeVar

from app.external.arxiv_client import ArxivClient
from app.external.http import ExternalError, ExternalHttpClient
from app.external.openalex_client import OpenAlexClient
from app.services.metadata.publishers import publisher_of

_TITLE_MATCH = 0.93
_TAG = re.compile(r"<[^>]+>")
_S2_MATCH = "https://api.semanticscholar.org/graph/v1/paper/search/match"
_S2_FIELDS = "title,authors,year,venue,externalIds,abstract"


def _norm_title(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def same_title(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    x, y = _norm_title(a), _norm_title(b)
    return x == y or SequenceMatcher(None, x, y).ratio() >= _TITLE_MATCH


def _bare_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return doi.lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/").strip() or None


def _unescape(text: str) -> str:
    # Crossref double-escapes some names ("Computers &amp;amp; Informatics")
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return " ".join(text.split())


def _plain(text: str | None) -> str | None:
    """An abstract as plain text (Crossref's are JATS-tagged)."""
    if not text:
        return None
    out = _unescape(_TAG.sub(" ", text))
    return re.sub(r"^(?i:abstract)\s*", "", out).strip() or None


def _inverted(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    return " ".join(w for _p, w in sorted((p, w) for w, ps in index.items() for p in ps)) or None


@dataclass(frozen=True)
class PaperMetadata:
    matched_by: str  # "doi" | "title"
    sources: list[str] = field(default_factory=list)
    doi: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    publisher: str | None = None
    abstract: str | None = None
    url: str | None = None


@dataclass
class _Found:
    """One source's answer."""

    source: str
    doi: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    publisher: str | None = None
    abstract: str | None = None
    url: str | None = None


def _from_crossref(message: dict[str, Any]) -> _Found:
    issued = ((message.get("issued") or {}).get("date-parts") or [[None]])[0]
    container = message.get("container-title") or []
    return _Found(
        source="crossref",
        doi=_bare_doi(message.get("DOI")),
        title=(message.get("title") or [None])[0],
        authors=[
            name
            for a in message.get("author") or []
            if isinstance(a, dict) and (name := " ".join(p for p in (a.get("given"), a.get("family")) if p).strip())
        ],
        year=issued[0] if issued and isinstance(issued[0], int) else None,
        venue=_unescape(container[0]) if container else None,
        publisher=message.get("publisher"),
        abstract=_plain(message.get("abstract")),
    )


def _from_openalex(work: dict[str, Any]) -> _Found:
    source = (work.get("primary_location") or {}).get("source") or {}
    return _Found(
        source="openalex",
        doi=_bare_doi(work.get("doi")),
        title=work.get("title") or work.get("display_name"),
        authors=[n for a in work.get("authorships") or [] if (n := ((a or {}).get("author") or {}).get("display_name"))],
        year=work.get("publication_year"),
        venue=source.get("display_name"),
        publisher=source.get("host_organization_name"),
        abstract=_inverted(work.get("abstract_inverted_index")),
        url=work.get("id"),
    )


def _from_s2(paper: dict[str, Any]) -> _Found:
    ids = paper.get("externalIds") or {}
    return _Found(
        source="semantic_scholar",
        doi=_bare_doi(ids.get("DOI")),
        title=paper.get("title"),
        authors=[a["name"] for a in paper.get("authors") or [] if isinstance(a, dict) and a.get("name")],
        year=paper.get("year"),
        venue=paper.get("venue") or None,
        abstract=paper.get("abstract"),
        url=f"https://arxiv.org/abs/{ids['ArXiv']}" if ids.get("ArXiv") else None,
    )


async def _json(http: ExternalHttpClient, url: str, params: dict[str, Any] | None = None) -> Any:
    resp = await http.get_response(url, params=params)
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


async def _crossref_by_doi(http: ExternalHttpClient, doi: str) -> _Found | None:
    body = await _json(http, "https://api.crossref.org/works/" + doi)
    message = (body or {}).get("message") if isinstance(body, dict) else None
    return _from_crossref(message) if isinstance(message, dict) else None


async def _crossref_by_title(http: ExternalHttpClient, title: str) -> _Found | None:
    body = await _json(http, "https://api.crossref.org/works", {"query.bibliographic": title, "rows": 5})
    items = ((body or {}).get("message") or {}).get("items") if isinstance(body, dict) else None
    for item in items or []:
        if isinstance(item, dict) and same_title((item.get("title") or [None])[0], title):
            return _from_crossref(item)
    return None


async def _s2_by_title(http: ExternalHttpClient, title: str) -> _Found | None:
    body = await _json(http, _S2_MATCH, {"query": title, "fields": _S2_FIELDS})
    papers = body.get("data") if isinstance(body, dict) else None
    for paper in papers or []:
        if isinstance(paper, dict) and same_title(paper.get("title"), title):
            return _from_s2(paper)
    return None


async def _arxiv_by_title(http: ExternalHttpClient, title: str) -> _Found | None:
    words = re.findall(r"[A-Za-z0-9]+", title)[:12]
    if not words:
        return None
    for record in await ArxivClient(http).search_query("ti:" + " AND ti:".join(words), max_results=5):
        if same_title(record.title, title):
            return _Found(
                source="arxiv",
                title=record.title,
                authors=list(record.authors),
                year=record.year,
                abstract=record.abstract,
                url=record.url,
            )
    return None


T = TypeVar("T")


async def _try(step: Awaitable[T | None]) -> T | None:
    try:
        return await step
    except ExternalError:
        return None  # that source is unavailable now; the next one may answer


async def find_metadata(http: ExternalHttpClient, *, doi: str | None, title: str | None) -> PaperMetadata | None:
    """The paper's record, matched by its DOI, else by its exact title."""
    found: list[_Found] = []
    doi = _bare_doi(doi)
    matched_by = "doi" if doi else "title"
    if doi:
        if hit := await _try(_crossref_by_doi(http, doi)):
            found.append(hit)
        if work := await _try(OpenAlexClient(http).get_work(doi)):
            found.append(_from_openalex(work))
    if title and not found:
        for step in (_crossref_by_title, _s2_by_title, _arxiv_by_title):
            if hit := await _try(step(http, title)):
                found.append(hit)
                break
        # a DOI found by title is followed for what the title match didn't carry
        title_doi = next((f.doi for f in found if f.doi), None)
        if (
            title_doi
            and not any(f.source == "openalex" for f in found)
            and (work := await _try(OpenAlexClient(http).get_work(title_doi)))
        ):
            found.append(_from_openalex(work))
    if not found:
        return None

    def first(name: str) -> Any:
        return next((v for f in found if (v := getattr(f, name))), None)

    found_doi = first("doi")
    venue = first("venue")
    return PaperMetadata(
        matched_by=matched_by,
        sources=[f.source for f in found],
        doi=found_doi,
        title=first("title"),
        authors=first("authors") or [],
        year=first("year"),
        venue=_unescape(venue) if venue else None,
        publisher=publisher_of(first("publisher"), found_doi),
        # an abstract is preferred from the sources that publish the paper's own (OpenAlex, S2, arXiv)
        abstract=next((f.abstract for f in sorted(found, key=lambda f: f.source == "crossref") if f.abstract), None),
        url=f"https://doi.org/{found_doi}" if found_doi else first("url"),
    )
