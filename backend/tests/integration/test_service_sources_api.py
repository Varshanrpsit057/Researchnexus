"""Settings > Sources & full text (remediation, 2026-10-06): what each
scholarly source is used for, how it is set up (never a key's value), and a
check that asks each one a single question now."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from app.config import Settings
from app.external.http import ExternalHttpClient
from app.services.sources import SOURCES, check_sources
from tests.auth_helpers import ANONYMOUS
from tests.integration.test_fulltext_api import _client
from tests.integration.test_workspaces_api import _headers, _token


def test_the_sources_say_how_they_are_set_up_and_never_show_a_key(tmp_path: Path) -> None:
    client = _client(tmp_path, openalex_api_key="secret-openalex-key", contact_email="reader@example.com")
    token = _token(client)
    assert client.get("/api/v1/service/sources", headers=ANONYMOUS).status_code == 401
    resp = client.get("/api/v1/service/sources", headers=_headers(token))
    assert resp.status_code == 200
    assert "secret-openalex-key" not in resp.text and "reader@example.com" not in resp.text
    body = resp.json()
    assert body["contact_email_set"] is True
    by_id = {s["id"]: s for s in body["sources"]}
    assert set(by_id) == {"openalex", "semantic_scholar", "arxiv", "crossref", "dblp", "core", "europepmc", "unpaywall"}
    assert by_id["openalex"]["key"] == "configured" and by_id["core"]["key"] == "not_set" and by_id["arxiv"]["key"] == "none"
    assert by_id["unpaywall"]["available"] is True and by_id["unpaywall"]["used_for"] == ["full_text"]


def test_the_publishers_a_reader_can_prefer() -> None:
    from app.services.metadata.publishers import known_publishers

    known = known_publishers()
    assert {"IEEE", "Springer", "ACM", "Elsevier", "MDPI", "Wiley", "ACL"} <= set(known)
    assert known == sorted(known, key=str.lower) and len(known) == len(set(known))


def test_checking_the_sources_asks_each_once_and_says_how_it_answered() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        if request.url.host == "api.openalex.org":
            return httpx.Response(429, headers={"Retry-After": "1500"})
        if request.url.host == "api.semanticscholar.org":
            return httpx.Response(503)
        if request.url.host == "api.core.ac.uk":
            return httpx.Response(401)
        if request.url.host == "api.unpaywall.org":
            assert request.url.params["email"] == "reader@example.com"
        return httpx.Response(200, json={})

    settings = Settings(_env_file=None, jwt_secret="x", contact_email="reader@example.com")  # type: ignore[call-arg]
    http = ExternalHttpClient(transport=httpx.MockTransport(handler), max_retries=0)
    results = {r["id"]: r for r in asyncio.run(check_sources(settings, http))}
    assert len(asked) == len(SOURCES)  # one question each
    assert results["openalex"]["status"] == "limited" and "25 min" in str(results["openalex"]["detail"])
    assert results["semantic_scholar"]["status"] == "unreachable"
    assert results["core"]["status"] == "refused"
    assert {results[s]["status"] for s in ("arxiv", "crossref", "dblp", "europepmc", "unpaywall")} == {"ok"}

    # without a contact email Unpaywall isn't asked at all
    asked.clear()
    bare = Settings(_env_file=None, jwt_secret="x")  # type: ignore[call-arg]
    results = {r["id"]: r for r in asyncio.run(check_sources(bare, http))}
    assert results["unpaywall"]["status"] == "not_set_up" and "api.unpaywall.org" not in asked
