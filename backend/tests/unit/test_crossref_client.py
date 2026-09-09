from __future__ import annotations

import asyncio

import httpx
import pytest

from app.domain.candidate import CandidateSource
from app.external.crossref_client import CrossrefClient
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse

_JSON = {
    "status": "ok",
    "message": {
        "DOI": "10.1109/BigData62323.2024.10825310",
        "title": ["Empowering Meta-Analysis: Leveraging Large Language Models for Scientific Synthesis"],
        "author": [{"given": "Jane", "family": "Doe"}, {"family": "Smith"}],
        "published": {"date-parts": [[2024, 12, 15]]},
        "container-title": ["2024 IEEE International Conference on Big Data (BigData)"],
        "URL": "https://doi.org/10.1109/BigData62323.2024.10825310",
        "type": "proceedings-article",
    },
}


def _client(status: int, payload: object) -> CrossrefClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.crossref.org" in str(request.url)
        if isinstance(payload, str):
            return httpx.Response(status, text=payload)
        return httpx.Response(status, json=payload)

    return CrossrefClient(ExternalHttpClient(transport=httpx.MockTransport(handler)))


def test_lookup_parses_message() -> None:
    rec = asyncio.run(_client(200, _JSON).lookup_doi("10.1109/BigData62323.2024.10825310"))
    assert rec is not None
    assert rec.source == CandidateSource.CROSSREF
    assert rec.doi == "10.1109/BigData62323.2024.10825310"
    assert rec.title.startswith("Empowering Meta-Analysis")
    assert rec.authors == ["Jane Doe", "Smith"]
    assert rec.year == 2024
    assert rec.venue == "2024 IEEE International Conference on Big Data (BigData)"
    assert rec.url == "https://doi.org/10.1109/BigData62323.2024.10825310"


def test_unknown_doi_returns_none() -> None:
    assert asyncio.run(_client(404, {"status": "error"}).lookup_doi("10.0/nope")) is None


def test_malformed_body_raises_typed_error() -> None:
    with pytest.raises(MalformedUpstreamResponse):
        asyncio.run(_client(200, "<html>not json</html>").lookup_doi("10.1/x"))


def test_message_missing_title_raises_typed_error() -> None:
    with pytest.raises(MalformedUpstreamResponse):
        asyncio.run(_client(200, {"status": "ok", "message": {"DOI": "10.1/x"}}).lookup_doi("10.1/x"))
