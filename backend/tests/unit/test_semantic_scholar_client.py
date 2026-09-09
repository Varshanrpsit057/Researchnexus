from __future__ import annotations

import asyncio

import httpx
import pytest

from app.domain.candidate import CandidateSource
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse
from app.external.semantic_scholar_client import SemanticScholarClient

_JSON = {
    "total": 2,
    "data": [
        {
            "paperId": "abc123",
            "title": "Retrieval-Augmented Generation",
            "abstract": "We propose RAG.",
            "year": 2020,
            "authors": [{"authorId": "1", "name": "Patrick Lewis"}, {"authorId": "2", "name": "Ethan Perez"}],
            "externalIds": {"DOI": "10.5555/abc", "ArXiv": "2005.11401", "CorpusId": 111},
            "venue": "NeurIPS",
            "url": "https://www.semanticscholar.org/paper/abc123",
        },
        {
            "paperId": "def456",
            "title": "A Preprint",
            "abstract": None,
            "year": 2023,
            "authors": [{"authorId": "3", "name": "Jane Doe"}],
            "externalIds": {"ArXiv": "2301.00001"},
            "venue": "",
            "url": "https://www.semanticscholar.org/paper/def456",
        },
    ],
}


def _client(payload: object) -> SemanticScholarClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.semanticscholar.org" in str(request.url)
        return httpx.Response(200, json=payload)

    return SemanticScholarClient(ExternalHttpClient(transport=httpx.MockTransport(handler)))


def test_parses_data_list() -> None:
    records = asyncio.run(_client(_JSON).search("rag", max_results=10))
    assert len(records) == 2
    first = records[0]
    assert first.source == CandidateSource.SEMANTIC_SCHOLAR
    assert first.source_native_id == "abc123"
    assert first.doi == "10.5555/abc"
    assert first.arxiv_id == "2005.11401"
    assert first.authors == ["Patrick Lewis", "Ethan Perez"]
    assert first.year == 2020
    assert first.venue == "NeurIPS"
    assert first.is_preprint is False


def test_arxiv_only_no_venue_is_preprint() -> None:
    records = asyncio.run(_client(_JSON).search("q", max_results=10))
    assert records[1].is_preprint is True
    assert records[1].venue is None


def test_empty_data_returns_empty_list() -> None:
    assert asyncio.run(_client({"total": 0, "data": []}).search("q", max_results=10)) == []


def test_missing_data_key_raises_typed_error() -> None:
    with pytest.raises(MalformedUpstreamResponse):
        asyncio.run(_client({"total": 0}).search("q", max_results=10))
