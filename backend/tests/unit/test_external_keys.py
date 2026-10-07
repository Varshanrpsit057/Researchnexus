"""Source credentials go to their own host as headers, never in a URL
(remediation Phase 8: OpenAlex's keyless daily budget, shared by a whole
network, runs out; a free key has its own)."""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.external.http import ExternalHttpClient
from app.external.keys import source_headers


def test_no_keys_means_no_headers() -> None:
    assert source_headers(Settings(_env_file=None)) is None  # type: ignore[call-arg]


def test_each_key_goes_only_to_its_own_host_and_never_into_the_url() -> None:
    settings = Settings(_env_file=None, openalex_api_key="oa-test", semantic_scholar_api_key="s2-test")  # type: ignore[call-arg]
    seen: dict[str, tuple[str | None, str | None, str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = (request.headers.get("authorization"), request.headers.get("x-api-key"), str(request.url))
        return httpx.Response(200, json={"results": [], "data": []})

    client = ExternalHttpClient(transport=httpx.MockTransport(handler), host_headers=source_headers(settings))

    async def calls() -> None:
        await client.get_json("https://api.openalex.org/works", params={"search": "q"})
        await client.get_json("https://api.semanticscholar.org/graph/v1/paper/search", params={"query": "q"})
        await client.get_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": "q"})

    asyncio.run(calls())
    assert seen["api.openalex.org"][:2] == ("Bearer oa-test", None)
    assert seen["api.semanticscholar.org"][:2] == (None, "s2-test")
    assert seen["www.ebi.ac.uk"][:2] == (None, None)
    assert not any("oa-test" in url or "s2-test" in url for _, _, url in seen.values())
