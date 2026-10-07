"""Crossref works client -- DOI -> canonical bibliographic metadata
(Architecture §7: "Crossref (DOI metadata)"). Used to enrich / adjudicate a
candidate that already has a DOI from another source; not a search client.
An unknown DOI (HTTP 404) is a normal outcome and returns `None`.
"""

from __future__ import annotations

import json
from typing import Any

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse

_BASE_URL = "https://api.crossref.org/works/"
_SEARCH_URL = "https://api.crossref.org/works"
# what a reader means by a paper: articles, proceedings papers, chapters, preprints
_PAPER_TYPES = "type:journal-article,type:proceedings-article,type:book-chapter,type:posted-content"
_SEARCH_FIELDS = "DOI,title,author,issued,container-title,publisher,abstract,type,URL"


class CrossrefClient:
    def __init__(self, http: ExternalHttpClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 25) -> list[RawExternalRecord]:
        """Publishers' own records matching the query (remediation,
        2026-10-02): IEEE, Springer, ACM and Elsevier deposit theirs here."""
        body = await self._http.get_json(
            _SEARCH_URL,
            params={"query.bibliographic": query, "rows": max_results, "select": _SEARCH_FIELDS, "filter": _PAPER_TYPES},
        )
        try:
            items = body["message"]["items"]
        except (KeyError, TypeError) as exc:
            raise MalformedUpstreamResponse("Crossref: search response missing message.items") from exc
        records = []
        for item in items or []:
            try:
                records.append(_message_to_record(item))
            except MalformedUpstreamResponse:
                continue  # an untitled record isn't a paper to show
        return records

    async def lookup_doi(self, doi: str) -> RawExternalRecord | None:
        resp = await self._http.get_response(_BASE_URL + doi.strip())
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise MalformedUpstreamResponse(f"Crossref: HTTP {resp.status_code} for {doi}")
        try:
            message = json.loads(resp.text)["message"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MalformedUpstreamResponse(f"Crossref: unexpected body for {doi}") from exc
        return _message_to_record(message)


def _message_to_record(message: dict[str, Any]) -> RawExternalRecord:
    titles = message.get("title") or []
    if not titles:
        raise MalformedUpstreamResponse("Crossref: message has no title")
    return RawExternalRecord(
        source=CandidateSource.CROSSREF,
        source_native_id=message.get("DOI"),
        doi=message.get("DOI"),
        title=titles[0],
        authors=_authors(message.get("author") or []),
        year=_year(message),
        abstract=(message.get("abstract") or None),
        venue=_first(message.get("container-title")),
        url=message.get("URL"),
        is_preprint=message.get("type") == "posted-content",
        publisher=message.get("publisher"),
    )


def _authors(raw: list[dict[str, Any]]) -> list[str]:
    names = []
    for a in raw:
        full = " ".join(part for part in (a.get("given"), a.get("family")) if part).strip()
        if full:
            names.append(full)
    return names


def _year(message: dict[str, Any]) -> int | None:
    for key in ("published", "published-print", "published-online", "issued"):
        parts = ((message.get(key) or {}).get("date-parts") or [[]])[0]
        if parts and isinstance(parts[0], int):
            return parts[0]
    return None


def _first(value: list[str] | None) -> str | None:
    return value[0] if value else None
