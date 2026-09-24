"""Europe PMC REST search client (JSON, keyless). Covers the life sciences
and biomedicine -- PubMed, PubMed Central and preprint servers -- which
arXiv and a CS-leaning keyword search reach poorly. `resultType=core`
returns abstracts, which the relevance ranking needs.

Returns `RawExternalRecord`s; canonicalisation is
app/services/normalize/canonical.py's job, not this module's.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse

_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_TAG_RE = re.compile(r"<[^>]+>")


class EuropePmcClient:
    def __init__(self, http: ExternalHttpClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 25) -> list[RawExternalRecord]:
        body = await self._http.get_json(
            _BASE_URL,
            params={"query": query, "format": "json", "resultType": "core", "pageSize": max_results},
        )
        results = ((body or {}).get("resultList") or {}).get("result") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise MalformedUpstreamResponse("Europe PMC: response missing `resultList.result`")
        return [self._result_to_record(r) for r in results if isinstance(r, dict) and r.get("title")]

    @staticmethod
    def _result_to_record(r: dict[str, Any]) -> RawExternalRecord:
        source = r.get("source")
        native_id = r.get("id")
        journal = ((r.get("journalInfo") or {}).get("journal") or {}).get("title")
        pub_types = ((r.get("pubTypeList") or {}).get("pubType")) or []
        year = r.get("pubYear")
        return RawExternalRecord(
            source=CandidateSource.EUROPE_PMC,
            source_native_id=f"{source}:{native_id}" if source and native_id else None,
            doi=r.get("doi"),
            title=_clean(r.get("title") or "").rstrip("."),
            authors=_authors(r),
            year=int(year) if isinstance(year, str) and year.isdigit() else None,
            abstract=_clean(r.get("abstractText") or "") or None,
            venue=journal,
            url=f"https://europepmc.org/article/{source}/{native_id}" if source and native_id else None,
            is_preprint=source == "PPR" or "Preprint" in pub_types,
        )


def _clean(text: str) -> str:
    # abstracts carry inline markup (<h4>, <i>, <sup>) -- keep only the text
    return " ".join(_TAG_RE.sub(" ", text).split())


def _authors(r: dict[str, Any]) -> list[str]:
    full = ((r.get("authorList") or {}).get("author")) or []
    names = [str(a["fullName"]) for a in full if isinstance(a, dict) and a.get("fullName")]
    if names:
        return names
    return [n.strip() for n in (r.get("authorString") or "").rstrip(".").split(",") if n.strip()]
