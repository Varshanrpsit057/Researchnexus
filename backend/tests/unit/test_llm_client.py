from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.domain.user import LlmProvider
from app.llm.client import ChatMessage
from app.llm.providers.openai_compat import OpenAiCompatClient


class _Fact(BaseModel):
    answer: str


def test_chat_returns_message_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello there"}}]})

    client = OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = asyncio.run(client.chat(api_key="sk-x", model="test-model", messages=[ChatMessage(role="user", content="hi")]))
    assert result.content == "hello there"


def test_structured_parses_valid_json_on_first_try() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer": "42"}'}}]})

    client = OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = asyncio.run(
        client.structured(api_key="sk-x", model="test-model", messages=[ChatMessage(role="user", content="hi")], schema=_Fact)
    )
    assert result.answer == "42"


def test_structured_repairs_invalid_json_once_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer": "repaired"}'}}]})

    client = OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = asyncio.run(
        client.structured(api_key="sk-x", model="test-model", messages=[ChatMessage(role="user", content="hi")], schema=_Fact)
    )
    assert result.answer == "repaired"
    assert calls["count"] == 2


def test_structured_raises_typed_failure_after_repair_also_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "still not json"}}]})

    client = OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(json.JSONDecodeError):
        asyncio.run(
            client.structured(
                api_key="sk-x", model="test-model", messages=[ChatMessage(role="user", content="hi")], schema=_Fact
            )
        )
