"""arXiv API client (Atom feed). Parses with `defusedxml` (an XXE / billion-laughs-safe drop-in for
`xml.etree.ElementTree`) -- the `feedparser` / `arxiv` dependencies the
Roadmap floats are not needed for the handful of fields Phase 4 uses.
`defusedxml` is the one dependency Phase 4 adds, and only because an
automated security check (rightly) flags stdlib XML parsing of a network
response.

Returns `RawExternalRecord`s; canonicalisation is
app/services/normalize/canonical.py's job, not this module's.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ET

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse

_BASE_URL = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


class ArxivClient:
    def __init__(self, http: ExternalHttpClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 25) -> list[RawExternalRecord]:
        text = await self._http.get_text(
            _BASE_URL, params={"search_query": f"all:{query}", "start": 0, "max_results": max_results}
        )
        try:
            root = ET.fromstring(text)
        except ParseError as exc:
            raise MalformedUpstreamResponse(f"arXiv: unparseable Atom feed: {exc}") from exc
        return [self._entry_to_record(e) for e in root.findall(f"{_ATOM}entry")]

    @staticmethod
    def _entry_to_record(entry: Element) -> RawExternalRecord:
        title = _text(entry.find(f"{_ATOM}title"))
        abstract = _text(entry.find(f"{_ATOM}summary"))
        raw_id = _text(entry.find(f"{_ATOM}id"))
        published = _text(entry.find(f"{_ATOM}published"))
        journal_ref = _text(entry.find(f"{_ARXIV}journal_ref"))
        doi = _text(entry.find(f"{_ARXIV}doi")) or None
        authors = [
            _text(name)
            for a in entry.findall(f"{_ATOM}author")
            if (name := a.find(f"{_ATOM}name")) is not None and _text(name)
        ]
        url = None
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("rel") == "alternate":
                url = link.get("href")

        year = int(published[:4]) if published[:4].isdigit() else None
        return RawExternalRecord(
            source=CandidateSource.ARXIV,
            source_native_id=raw_id or None,
            arxiv_id=raw_id or None,
            doi=doi,
            title=title,
            authors=authors,
            year=year,
            abstract=abstract or None,
            venue=journal_ref or None,
            url=url,
            is_preprint=not journal_ref,
        )


def _text(el: Element | None) -> str:
    return " ".join(el.text.split()) if el is not None and el.text else ""
