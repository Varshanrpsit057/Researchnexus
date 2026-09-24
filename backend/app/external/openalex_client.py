"""OpenAlex `/works` client (JSON, keyless). Returns `RawExternalRecord`s;
canonicalisation is app/services/normalize/canonical.py's job.

Abstracts arrive as an inverted index ({word: [positions]}) and are
reconstructed here.
"""

from __future__ import annotations

from typing import Any

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse

_BASE_URL = "https://api.openalex.org/works"
# only the fields the records are built from: full work objects are several
# times larger, and on a busy day that size is the difference in latency
_SELECT = "id,doi,title,display_name,publication_year,authorships,abstract_inverted_index,primary_location,type"
_SELECT_SEED = f"{_SELECT},referenced_works,related_works"
_PREPRINT_SOURCE_TYPES = {"repository"}


class OpenAlexClient:
    def __init__(self, http: ExternalHttpClient) -> None:
        self._http = http

    async def search(self, query: str, *, max_results: int = 25) -> list[RawExternalRecord]:
        body = await self._http.get_json(_BASE_URL, params={"search": query, "per_page": max_results, "select": _SELECT})
        return self._records_from_results(body)

    async def search_works(self, query: str, *, per_page: int = 5) -> list[dict[str, Any]]:
        """Raw work dicts (with `referenced_works` / `related_works`), for
        resolving a seed paper by its title."""
        body = await self._http.get_json(_BASE_URL, params={"search": query, "per_page": per_page, "select": _SELECT_SEED})
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise MalformedUpstreamResponse("OpenAlex: response missing a `results` list")
        return [w for w in body["results"] if isinstance(w, dict)]

    async def get_work(self, id_or_doi: str) -> dict[str, Any] | None:
        """Fetch a single work by OpenAlex id or DOI. Returns the raw work
        dict (the citation strategy needs its `referenced_works`), or None
        if the id is unknown / the body is not a work."""
        key = id_or_doi if id_or_doi.startswith("http") else f"https://doi.org/{id_or_doi}"
        resp = await self._http.get_response(f"{_BASE_URL}/{key}")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise MalformedUpstreamResponse(f"OpenAlex: HTTP {resp.status_code} for {id_or_doi}")
        import json as _json

        try:
            work = _json.loads(resp.text)
        except _json.JSONDecodeError as exc:
            raise MalformedUpstreamResponse(f"OpenAlex: non-JSON work for {id_or_doi}") from exc
        return work if isinstance(work, dict) and work.get("id") else None

    async def works_by_ids(self, openalex_ids: list[str], *, per_page: int = 50) -> list[RawExternalRecord]:
        if not openalex_ids:
            return []
        short = [i.rstrip("/").rsplit("/", 1)[-1] for i in openalex_ids]
        body = await self._http.get_json(
            _BASE_URL, params={"filter": f"openalex_id:{'|'.join(short)}", "per_page": per_page, "select": _SELECT}
        )
        return self._records_from_results(body)

    async def works_citing(self, openalex_id: str, *, per_page: int = 25) -> list[RawExternalRecord]:
        short = openalex_id.rstrip("/").rsplit("/", 1)[-1]
        body = await self._http.get_json(
            _BASE_URL, params={"filter": f"cites:{short}", "per_page": per_page, "select": _SELECT}
        )
        return self._records_from_results(body)

    @classmethod
    def _records_from_results(cls, body: object) -> list[RawExternalRecord]:
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise MalformedUpstreamResponse("OpenAlex: response missing a `results` list")
        return [cls._work_to_record(w) for w in body["results"] if isinstance(w, dict)]

    @staticmethod
    def _work_to_record(work: dict[str, Any]) -> RawExternalRecord:
        source = (work.get("primary_location") or {}).get("source") or {}
        authors = [
            name
            for a in work.get("authorships") or []
            if (name := ((a or {}).get("author") or {}).get("display_name"))
        ]
        is_preprint = work.get("type") == "preprint" or source.get("type") in _PREPRINT_SOURCE_TYPES
        return RawExternalRecord(
            source=CandidateSource.OPENALEX,
            source_native_id=work.get("id"),
            doi=work.get("doi"),
            title=work.get("title") or work.get("display_name") or "",
            authors=authors,
            year=work.get("publication_year"),
            abstract=_abstract_from_inverted_index(work.get("abstract_inverted_index")),
            venue=source.get("display_name"),
            url=work.get("id"),
            is_preprint=is_preprint,
        )


def _abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positioned: list[tuple[int, str]] = [(pos, word) for word, positions in index.items() for pos in positions]
    positioned.sort()
    return " ".join(word for _pos, word in positioned) or None
