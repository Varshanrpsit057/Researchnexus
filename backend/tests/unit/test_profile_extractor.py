from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.user import LlmProvider
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.services.profile.extractor import ProfileExtractionFailed, extract_profile

_VALID_EXTRACTION_JSON = json.dumps(
    {
        "domain": {"value": "NLP", "quote": "This paper is about NLP."},
        "subdomains": {"items": []},
        "research_problem": {"value": "Solving Y", "quote": None},
        "research_questions": {"items": []},
        "objectives": {"items": []},
        "keywords": ["nlp"],
        "methods": {"items": []},
        "models": {"items": []},
        "algorithms": {"items": []},
        "datasets": {"items": []},
        "evaluation_metrics": {"items": []},
        "findings": {"items": []},
        "limitations": {"items": []},
        "future_work": {"items": []},
        "important_entities": {"items": []},
        "cited_methods": {"items": []},
        "candidate_search_queries": [],
    }
)


def _chunks() -> list[PaperChunk]:
    return [
        PaperChunk(
            chunk_id="chk_1",
            paper_id="pap_1",
            section="Abstract",
            section_order=0,
            page=1,
            char_start=0,
            char_end=25,
            kind=ChunkKind.ABSTRACT,
            text="This paper is about NLP.",
            token_count=5,
        )
    ]


def test_extract_profile_returns_parsed_extraction_and_token_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _VALID_EXTRACTION_JSON}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7},
            },
        )

    client = OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    extraction, tokens = asyncio.run(
        extract_profile(client, api_key="sk-x", model="test-model", chunks=_chunks(), max_context_chars=10_000)
    )
    assert extraction.domain.value == "NLP"
    assert tokens.prompt == 42
    assert tokens.completion == 7


def test_extract_profile_repairs_malformed_json_once_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": _VALID_EXTRACTION_JSON}}]})

    client = OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    extraction, _tokens = asyncio.run(
        extract_profile(client, api_key="sk-x", model="test-model", chunks=_chunks(), max_context_chars=10_000)
    )
    assert extraction.domain.value == "NLP"
    assert calls["count"] == 2


def test_extract_profile_raises_typed_failure_when_repair_also_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "still not json"}}]})

    client = OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProfileExtractionFailed):
        asyncio.run(extract_profile(client, api_key="sk-x", model="test-model", chunks=_chunks(), max_context_chars=10_000))


def test_extract_profile_lets_provider_errors_propagate_uncaught() -> None:
    from app.llm.client import LlmProviderError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid api key"})

    client = OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(LlmProviderError):
        asyncio.run(extract_profile(client, api_key="sk-bad", model="test-model", chunks=_chunks(), max_context_chars=10_000))
