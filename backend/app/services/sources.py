"""The scholarly sources ResearchNexus reads, and how each is doing
(remediation, 2026-10-06: Settings > Sources & full text).

`describe_sources` says what each source is used for and how it is set up
(a key configured, or keyless with that source's limits) -- never a key's
value. `check_sources` asks each one a single, cheap question now and
reports what came back: answered, limiting requests, refused, or out of
reach. One request per source, through the same allow-listed client the
pipelines use.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.config import Settings
from app.external.http import (
    ExternalError,
    ExternalHttpClient,
    UpstreamUnavailable,
    parse_retry_after,
)
from app.external.keys import source_headers


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    used_for: tuple[str, ...]  # "discovery", "records", "full_text"
    # how a key changes things; None when the source has no key
    key_setting: str | None
    keyless: str  # what using it without a key means
    probe_url: str
    probe_params: tuple[tuple[str, str], ...] = ()


SOURCES: tuple[Source, ...] = (
    Source(
        "openalex", "OpenAlex", ("discovery", "records", "full_text"), "RESEARCHNEXUS_OPENALEX_API_KEY",
        "A daily budget shared by everyone on this network's address",
        "https://api.openalex.org/works/W2741809807", (("select", "id"),),
    ),
    Source(
        "semantic_scholar", "Semantic Scholar", ("discovery", "records", "full_text"), "RESEARCHNEXUS_SEMANTIC_SCHOLAR_API_KEY",
        "About one request a second, often refused when busy",
        "https://api.semanticscholar.org/graph/v1/paper/arXiv:1706.03762", (("fields", "title"),),
    ),
    Source(
        "arxiv", "arXiv", ("discovery", "records", "full_text"), None,
        "Open; one request every three seconds",
        "https://export.arxiv.org/api/query", (("id_list", "1706.03762"), ("max_results", "1")),
    ),
    Source(
        "crossref", "Crossref", ("discovery", "records"), None,
        "Open; faster with a contact email",
        "https://api.crossref.org/works/10.1038/nature12373",
    ),
    Source(
        "dblp", "DBLP", ("discovery",), None,
        "Open; computer science only",
        "https://dblp.org/search/publ/api", (("q", "attention is all you need"), ("h", "1"), ("format", "json")),
    ),
    Source(
        "core", "CORE", ("discovery", "full_text"), "RESEARCHNEXUS_CORE_API_KEY",
        "A few requests a day without a key",
        "https://api.core.ac.uk/v3/search/works/", (("q", "attention"), ("limit", "1")),
    ),
    Source(
        "europepmc", "Europe PMC", ("discovery", "full_text"), None,
        "Open; life sciences and medicine",
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search", (("query", "attention"), ("format", "json"), ("pageSize", "1")),
    ),
    Source(
        "unpaywall", "Unpaywall", ("full_text",), None,
        "Open, but needs a contact email",
        "https://api.unpaywall.org/v2/10.1038/nature12373",
    ),
)


def _configured(source: Source, settings: Settings) -> bool:
    return {
        "openalex": bool(settings.openalex_api_key),
        "semantic_scholar": bool(settings.semantic_scholar_api_key),
        "core": bool(settings.core_api_key),
    }.get(source.id, False)


def describe_sources(settings: Settings) -> dict[str, object]:
    return {
        "contact_email_set": bool(settings.contact_email),
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "used_for": list(s.used_for),
                "key": ("configured" if _configured(s, settings) else "not_set") if s.key_setting else "none",
                "key_setting": s.key_setting,
                "keyless": s.keyless,
                # Unpaywall can't be asked at all without a contact email
                "available": bool(settings.contact_email) if s.id == "unpaywall" else True,
            }
            for s in SOURCES
        ],
    }


async def _check_one(http: ExternalHttpClient, source: Source, settings: Settings) -> dict[str, object]:
    params = dict(source.probe_params)
    if source.id == "unpaywall":
        if not settings.contact_email:
            return {"id": source.id, "status": "not_set_up", "detail": "No contact email is set, so it isn't asked."}
        params["email"] = settings.contact_email
    started = time.monotonic()
    try:
        resp = await http.get_response(source.probe_url, params=params or None)
    except UpstreamUnavailable as e:
        return {"id": source.id, "status": "unreachable", "http_status": e.status, "detail": "It didn't answer, or answered with a server error."}
    except ExternalError:
        return {"id": source.id, "status": "error", "detail": "The request couldn't be made."}
    ms = round((time.monotonic() - started) * 1000)
    code = resp.status_code
    if 200 <= code < 300:
        return {"id": source.id, "status": "ok", "http_status": code, "latency_ms": ms}
    if code == 429:
        wait = parse_retry_after(resp.headers.get("Retry-After"))
        detail = (f"It asks to wait {round(wait / 60)} min." if wait >= 90 else f"It asks to wait {round(wait)} s.") if wait else None
        return {"id": source.id, "status": "limited", "http_status": code, "latency_ms": ms, "detail": detail}
    if code in (401, 403):
        return {"id": source.id, "status": "refused", "http_status": code, "latency_ms": ms, "detail": "It refused the request; check its key."}
    return {"id": source.id, "status": "error", "http_status": code, "latency_ms": ms, "detail": f"It answered HTTP {code}."}


async def check_sources(settings: Settings, http: ExternalHttpClient | None = None) -> list[dict[str, object]]:
    client = http or ExternalHttpClient(timeout_s=8.0, max_retries=0, host_headers=source_headers(settings))
    return list(await asyncio.gather(*(_check_one(client, s, settings) for s in SOURCES)))
