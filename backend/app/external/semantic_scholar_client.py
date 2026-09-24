"""Semantic Scholar client (JSON; keyless by default, an optional free API
key raises the rate limit -- see ExternalHttpClient `host_headers`).

Keyword `search` plus the calls that make discovery relevance-first:
- `match_title`: resolve a seed that has no DOI to its S2 paper by exact
  title;
- `recommendations`: S2's "papers like this one" (SPECTER embeddings);
- `references` / `citations`: the seed's 1-hop citation neighbourhood.
S2 rate-limits strictly (about one request a second without a key), so the
discovery layer spaces calls to this host (`host_min_interval_s`) and uses
it for these few high-value calls rather than for broad keyword sweeps.
"""

from __future__ import annotations

from typing import Any

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.external.http import (
    ExternalHttpClient,
    MalformedUpstreamResponse,
    UpstreamRateLimited,
    UpstreamUnavailable,
)

_API = "https://api.semanticscholar.org"
_BASE_URL = f"{_API}/graph/v1/paper/search"
_MATCH_URL = f"{_API}/graph/v1/paper/search/match"
_PAPER_URL = f"{_API}/graph/v1/paper"
_RECOMMEND_URL = f"{_API}/recommendations/v1/papers/forpaper"
_FIELDS = "title,abstract,year,authors,externalIds,venue,url"


class SemanticScholarClient:
    def __init__(self, http: ExternalHttpClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 25) -> list[RawExternalRecord]:
        body = await self._http.get_json(
            _BASE_URL, params={"query": query, "limit": max_results, "fields": _FIELDS}
        )
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise MalformedUpstreamResponse("Semantic Scholar: response missing a `data` list")
        return [self._paper_to_record(p) for p in body["data"] if isinstance(p, dict)]

    async def match_title(self, title: str) -> dict[str, Any] | None:
        """S2's single best title match (`paperId`, `title`, `externalIds`),
        or None when it has none. The caller must still check the title is
        really the same paper."""
        body = await self._get_or_none(_MATCH_URL, {"query": title, "fields": "title,externalIds"})
        data = body.get("data") if isinstance(body, dict) else None
        return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None

    async def get_paper(self, ref: str) -> dict[str, Any] | None:
        """A paper by S2 id or a prefixed id such as `DOI:10.1/x` / `ARXIV:2101.00001`."""
        body = await self._get_or_none(f"{_PAPER_URL}/{ref}", {"fields": "title,externalIds"})
        return body if isinstance(body, dict) and body.get("paperId") else None

    async def recommendations(self, paper_id: str, *, limit: int = 50) -> list[RawExternalRecord]:
        body = await self._http.get_json(f"{_RECOMMEND_URL}/{paper_id}", params={"limit": limit, "fields": _FIELDS})
        if not isinstance(body, dict) or not isinstance(body.get("recommendedPapers"), list):
            raise MalformedUpstreamResponse("Semantic Scholar: recommendations missing `recommendedPapers`")
        return [self._paper_to_record(p) for p in body["recommendedPapers"] if isinstance(p, dict) and p.get("title")]

    async def references(self, paper_id: str, *, limit: int = 100) -> list[RawExternalRecord]:
        """Papers the given paper cites."""
        return await self._neighbours(paper_id, "references", "citedPaper", limit)

    async def citations(self, paper_id: str, *, limit: int = 100) -> list[RawExternalRecord]:
        """Papers that cite the given paper."""
        return await self._neighbours(paper_id, "citations", "citingPaper", limit)

    async def _neighbours(self, paper_id: str, edge: str, key: str, limit: int) -> list[RawExternalRecord]:
        body = await self._http.get_json(f"{_PAPER_URL}/{paper_id}/{edge}", params={"limit": limit, "fields": _FIELDS})
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise MalformedUpstreamResponse(f"Semantic Scholar: {edge} missing a `data` list")
        papers = [row.get(key) for row in body["data"] if isinstance(row, dict)]
        return [self._paper_to_record(p) for p in papers if isinstance(p, dict) and p.get("title")]

    async def _get_or_none(self, url: str, params: dict[str, Any]) -> Any:
        """GET where 404 means "no such paper" rather than a failure."""
        resp = await self._http.get_response(url, params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            raise UpstreamRateLimited(f"{url}: rate limited")
        if resp.status_code >= 400:
            raise UpstreamUnavailable(f"{url}: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise MalformedUpstreamResponse(f"{url}: response was not valid JSON") from exc

    @staticmethod
    def _paper_to_record(paper: dict[str, Any]) -> RawExternalRecord:
        ext = paper.get("externalIds") or {}
        venue = (paper.get("venue") or "").strip() or None
        arxiv_id = ext.get("ArXiv")
        return RawExternalRecord(
            source=CandidateSource.SEMANTIC_SCHOLAR,
            source_native_id=paper.get("paperId"),
            doi=ext.get("DOI"),
            arxiv_id=arxiv_id,
            title=paper.get("title") or "",
            authors=[name for a in paper.get("authors") or [] if (name := (a or {}).get("name"))],
            year=paper.get("year"),
            abstract=paper.get("abstract") or None,
            venue=venue,
            url=paper.get("url"),
            is_preprint=bool(arxiv_id) and venue is None,
        )
