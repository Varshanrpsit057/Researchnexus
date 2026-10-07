"""DBLP search (remediation, 2026-10-02): computer-science publications --
IEEE, ACM and Springer proceedings and journals -- with their DOIs. No key;
DBLP asks clients to keep a gentle pace (spaced per host by the caller).
DBLP indexes bibliographic records only, so its hits carry no abstract.
"""

from __future__ import annotations

from typing import Any

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse

_SEARCH_URL = "https://dblp.org/search/publ/api"


class DblpClient:
    def __init__(self, http: ExternalHttpClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 25) -> list[RawExternalRecord]:
        body = await self._http.get_json(_SEARCH_URL, params={"q": query, "format": "json", "h": max_results})
        try:
            hits = body["result"]["hits"].get("hit") or []
        except (KeyError, TypeError, AttributeError) as exc:
            raise MalformedUpstreamResponse("DBLP: response missing result.hits") from exc
        return [rec for h in hits if isinstance(h, dict) and (rec := _to_record(h.get("info") or {}))]


def _authors(raw: Any) -> list[str]:
    entries = (raw or {}).get("author") if isinstance(raw, dict) else None
    if isinstance(entries, dict):
        entries = [entries]
    names = []
    for a in entries or []:
        name = a.get("text") if isinstance(a, dict) else a
        if isinstance(name, str) and name.strip():
            # DBLP disambiguates namesakes with a number ("Wei Li 0001")
            names.append(" ".join(p for p in name.split() if not p.isdigit()))
    return names


def _to_record(info: dict[str, Any]) -> RawExternalRecord | None:
    title = str(info.get("title") or "").strip().rstrip(".")
    if not title:
        return None
    year = info.get("year")
    ee = info.get("ee")
    url = ee[0] if isinstance(ee, list) and ee else ee if isinstance(ee, str) else info.get("url")
    return RawExternalRecord(
        source=CandidateSource.DBLP,
        source_native_id=info.get("key"),
        doi=info.get("doi"),
        title=title,
        authors=_authors(info.get("authors")),
        year=int(year) if isinstance(year, str) and year.isdigit() else None,
        venue=info.get("venue") if isinstance(info.get("venue"), str) else None,
        url=url if isinstance(url, str) else None,
        is_preprint=info.get("type") == "Informal and Other Publications",
    )
