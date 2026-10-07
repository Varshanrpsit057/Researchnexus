"""CORE (core.ac.uk), the aggregator of the world's open-access repositories
(remediation, 2026-10-02): search, and the repository copy of a paper's full
text. Works without a key at a small hourly quota; a free key
(`RESEARCHNEXUS_CORE_API_KEY`, sent as a header) raises it.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse

# the trailing slash is CORE's canonical path (without it, CORE redirects)
_SEARCH_URL = "https://api.core.ac.uk/v3/search/works/"
_WORD = re.compile(r"[A-Za-z0-9]+")


def plain_query(text: str) -> str:
    """CORE's query language reads ':' and quotes as syntax: keep the words."""
    return " ".join(_WORD.findall(text))


class CoreClient:
    def __init__(self, http: ExternalHttpClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 25) -> list[RawExternalRecord]:
        words = plain_query(query)
        if not words:
            return []
        return await self._works(words, max_results)

    async def by_doi(self, doi: str) -> list[RawExternalRecord]:
        return await self._works(f'doi:"{doi}"', 3)

    async def by_title(self, title: str) -> list[RawExternalRecord]:
        words = plain_query(title)
        return await self._works(f'title:"{words}"', 5) if words else []

    async def _works(self, q: str, limit: int) -> list[RawExternalRecord]:
        body = await self._http.get_json(_SEARCH_URL, params={"q": q, "limit": limit})
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise MalformedUpstreamResponse("CORE: response missing a `results` list")
        return [rec for w in body["results"] if isinstance(w, dict) and (rec := _to_record(w))]


def download_url(record: RawExternalRecord) -> str | None:
    """The repository copy of the paper's PDF CORE holds, if any."""
    url = record.raw.get("downloadUrl")
    return url if isinstance(url, str) and url.startswith("https://") else None


def _to_record(work: dict[str, Any]) -> RawExternalRecord | None:
    title = str(work.get("title") or "").strip()
    if not title:
        return None
    ids = work.get("identifiers") or []
    arxiv = next((i.get("identifier") for i in ids if isinstance(i, dict) and i.get("type") == "ARXIV_ID"), None)
    year = work.get("yearPublished")
    return RawExternalRecord(
        source=CandidateSource.CORE,
        source_native_id=str(work.get("id")) if work.get("id") is not None else None,
        doi=work.get("doi"),
        arxiv_id=arxiv,
        title=title,
        authors=[a["name"] for a in work.get("authors") or [] if isinstance(a, dict) and a.get("name")],
        year=year if isinstance(year, int) else None,
        abstract=work.get("abstract") or None,
        venue=None,
        url=(work.get("links") or [{}])[0].get("url") if work.get("links") else None,
        publisher=work.get("publisher") or None,
        raw={"downloadUrl": work.get("downloadUrl")},
    )
