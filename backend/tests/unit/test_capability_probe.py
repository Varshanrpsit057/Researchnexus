from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.user import LlmProvider
from app.llm.capability_probe import probe


def _openai_compat_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer sk-test-key"
    payload = json.loads(request.read())
    if payload.get("response_format", {}).get("type") == "json_object":
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
    return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})


def _openai_compat_unauthorized_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": "invalid api key"})


def _gemini_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["x-goog-api-key"] == "gk-test-key"
    assert "key=" not in str(request.url)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "pong"}]}}]})


def test_openai_compatible_probe_reports_json_mode_and_latency() -> None:
    transport = httpx.MockTransport(_openai_compat_handler)
    result = asyncio.run(probe(LlmProvider.GROQ, "sk-test-key", transport=transport))
    assert result.success is True
    assert result.capabilities is not None
    assert result.capabilities.json_mode is True
    assert result.capabilities.streaming is True
    assert result.latency_ms is not None


def test_probe_reports_failure_on_bad_key_not_a_crash() -> None:
    transport = httpx.MockTransport(_openai_compat_unauthorized_handler)
    result = asyncio.run(probe(LlmProvider.GROQ, "sk-bad-key", transport=transport))
    assert result.success is False
    assert result.message is not None
    assert result.capabilities is None


def test_gemini_probe_sends_key_in_header_not_url() -> None:
    transport = httpx.MockTransport(_gemini_handler)
    result = asyncio.run(probe(LlmProvider.GEMINI, "gk-test-key", transport=transport))
    assert result.success is True
    assert result.capabilities is not None
