"""Downloading a paper's PDF (remediation Phase 7): every redirect hop is a
full-text source, the body is capped, and a landing page is not a PDF."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.external.allowlist import DisallowedHost
from app.external.http import ExternalHttpClient, NotAPdf, TooLarge, UpstreamUnavailable

PDF = b"%PDF-1.7\n" + b"x" * 200


def _client(handler) -> ExternalHttpClient:  # noqa: ANN001
    return ExternalHttpClient(transport=httpx.MockTransport(handler))


def test_a_doi_redirect_to_an_open_access_publisher_is_followed() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "doi.org":
            return httpx.Response(302, headers={"location": "https://www.mdpi.com/2076-3417/13/5/3120"})
        if request.url.path.endswith("3120"):
            return httpx.Response(301, headers={"location": "/2076-3417/13/5/3120/pdf"})
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})

    data, final = asyncio.run(_client(handler).get_pdf("https://doi.org/10.3390/app13053120", max_bytes=10_000))
    assert data == PDF and final == "https://www.mdpi.com/2076-3417/13/5/3120/pdf"
    assert len(seen) == 3


def test_a_redirect_into_the_private_network_is_refused_and_never_requested() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://169.254.169.254/latest/meta-data"})

    with pytest.raises(DisallowedHost):
        asyncio.run(_client(handler).get_pdf("https://doi.org/10.1/x", max_bytes=10_000))
    assert seen == ["doi.org"]


def test_a_redirect_to_a_public_repository_is_followed() -> None:
    # a DOI resolving to a small journal's own site (measured live: most open copies sit there)
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "doi.org":
            return httpx.Response(302, headers={"location": "https://jicet.org/article/download/1/2"})
        return httpx.Response(200, content=PDF)

    data, final = asyncio.run(_client(handler).get_pdf("https://doi.org/10.1/x", max_bytes=10_000))
    assert data == PDF and final == "https://jicet.org/article/download/1/2"


def test_a_landing_page_is_not_a_pdf() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Sign in to read</html>", headers={"content-type": "text/html"})

    with pytest.raises(NotAPdf, match="text/html"):
        asyncio.run(_client(handler).get_pdf("https://academic.oup.com/x/pdf", max_bytes=10_000))


def test_a_download_is_capped_whether_or_not_it_says_its_size() -> None:
    def declared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PDF, headers={"content-length": "99999999"})

    def undeclared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(PDF * 100))

    with pytest.raises(TooLarge):
        asyncio.run(_client(declared).get_pdf("https://arxiv.org/pdf/1", max_bytes=1000))
    with pytest.raises(TooLarge):
        asyncio.run(_client(undeclared).get_pdf("https://arxiv.org/pdf/1", max_bytes=1000))


def test_refusals_and_endless_redirects_are_failures_not_retries() -> None:
    calls = {"n": 0}

    def forbidden(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403)

    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url)})

    with pytest.raises(UpstreamUnavailable, match="HTTP 403"):
        asyncio.run(_client(forbidden).get_pdf("https://arxiv.org/pdf/1", max_bytes=1000))
    assert calls["n"] == 1
    with pytest.raises(UpstreamUnavailable, match="redirects"):
        asyncio.run(_client(loop).get_pdf("https://arxiv.org/pdf/1", max_bytes=1000))
