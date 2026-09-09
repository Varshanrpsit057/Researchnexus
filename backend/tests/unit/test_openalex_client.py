from __future__ import annotations

import asyncio

import httpx
import pytest

from app.domain.candidate import CandidateSource
from app.external.http import ExternalHttpClient, MalformedUpstreamResponse
from app.external.openalex_client import OpenAlexClient

_JSON = {
    "results": [
        {
            "id": "https://openalex.org/W2963403868",
            "doi": "https://doi.org/10.5555/ABC",
            "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
            "publication_year": 2020,
            "type": "article",
            "authorships": [
                {"author": {"display_name": "Patrick Lewis"}},
                {"author": {"display_name": "Ethan Perez"}},
            ],
            "primary_location": {"source": {"display_name": "NeurIPS", "type": "conference"}},
            "abstract_inverted_index": {"We": [0], "propose": [1], "RAG.": [2]},
        },
        {
            "id": "https://openalex.org/W999",
            "doi": None,
            "title": "A Preprint",
            "publication_year": 2023,
            "type": "preprint",
            "authorships": [{"author": {"display_name": "Jane Doe"}}],
            "primary_location": {"source": {"display_name": "arXiv", "type": "repository"}},
            "abstract_inverted_index": None,
        },
    ]
}


def _client(payload: object) -> OpenAlexClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.openalex.org" in str(request.url)
        return httpx.Response(200, json=payload)

    return OpenAlexClient(ExternalHttpClient(transport=httpx.MockTransport(handler)))


def test_parses_works_including_inverted_index_abstract() -> None:
    records = asyncio.run(_client(_JSON).search("rag", max_results=10))
    assert len(records) == 2
    first = records[0]
    assert first.source == CandidateSource.OPENALEX
    assert first.source_native_id == "https://openalex.org/W2963403868"
    assert first.doi == "https://doi.org/10.5555/ABC"
    assert first.title == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
    assert first.authors == ["Patrick Lewis", "Ethan Perez"]
    assert first.year == 2020
    assert first.abstract == "We propose RAG."
    assert first.venue == "NeurIPS"
    assert first.is_preprint is False


def test_preprint_type_and_repository_source_flag_is_preprint() -> None:
    records = asyncio.run(_client(_JSON).search("q", max_results=10))
    assert records[1].is_preprint is True
    assert records[1].abstract is None


def test_empty_results_returns_empty_list() -> None:
    assert asyncio.run(_client({"results": []}).search("q", max_results=10)) == []


def test_missing_results_key_raises_typed_error() -> None:
    with pytest.raises(MalformedUpstreamResponse):
        asyncio.run(_client({"meta": {"count": 0}}).search("q", max_results=10))


def test_non_dict_payload_raises_typed_error() -> None:
    with pytest.raises(MalformedUpstreamResponse):
        asyncio.run(_client([1, 2, 3]).search("q", max_results=10))
