"""Semantic Scholar Graph API client (JSON, keyless). **Fallback only** --
S2's rate limits are strict and its coverage overlaps arXiv/OpenAlex, so
the discovery layer (Phase 5) calls this only when the primary sources
came back thin (Architecture §7: "Semantic Scholar (fallback)"; Roadmap
Phase 4 risks: "S2 is fallback-only"). This module just implements the
client; the "when to fall back" decision is the caller's.
"""

from __future__ import annotations

from typing import Any

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse

_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
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
