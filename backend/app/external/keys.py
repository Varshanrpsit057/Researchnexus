"""Credentials the scholarly sources accept, each sent only to its own host
as a header -- never in a URL, never logged, never part of a cache key
(ExternalHttpClient's `host_headers`). Every source works without one; a key
raises that source's limits."""

from __future__ import annotations

from app.config import Settings


def source_headers(settings: Settings) -> dict[str, dict[str, str]] | None:
    headers: dict[str, dict[str, str]] = {}
    if settings.semantic_scholar_api_key:
        headers["api.semanticscholar.org"] = {"x-api-key": settings.semantic_scholar_api_key}
    if settings.openalex_api_key:
        headers["api.openalex.org"] = {"Authorization": f"Bearer {settings.openalex_api_key}"}
    if settings.contact_email:
        # the sources' "polite" access: a contact address in the User-Agent, not in the URL
        agent = {"User-Agent": f"ResearchNexus/0.1 (mailto:{settings.contact_email})"}
        for host in ("api.openalex.org", "api.crossref.org"):
            headers[host] = {**headers.get(host, {}), **agent}
    if settings.core_api_key:
        headers["api.core.ac.uk"] = {"Authorization": f"Bearer {settings.core_api_key}"}
    return headers or None
