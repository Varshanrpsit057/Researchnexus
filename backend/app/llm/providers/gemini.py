"""Gemini adapter -- a different request/response shape from the
OpenAI-compatible family (Architecture §7). Uses the `x-goog-api-key`
header rather than Gemini's `?key=` query-parameter auth form, so the key
is never placed in a URL (never logged in access logs, never in a proxy's
URL-based cache key).
"""

from __future__ import annotations

import json
import time

import httpx
from pydantic import ValidationError

from app.domain.user import LlmCapabilities
from app.llm.client import ChatMessage, ChatResult, LlmProviderError, T
from app.llm.schema_repair import build_repair_messages, parse_structured

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-1.5-flash"
# Gemini 1.5 models advertise a 1M-token context window; see the openai_compat
# module docstring note on why this is a static, documented approximation
# rather than a live-queried value.
_CONTEXT_TOKENS = 1_000_000


def _to_gemini_role(role: str) -> str:
    return "model" if role == "assistant" else "user"


class GeminiClient:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _generate(
        self, api_key: str, model: str, contents: list[dict[str, object]], generation_config: dict[str, object] | None = None
    ) -> httpx.Response:
        body: dict[str, object] = {"contents": contents}
        if generation_config:
            body["generationConfig"] = generation_config
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            return await client.post(
                f"{_BASE_URL}/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json=body,
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def chat(self, *, api_key: str, model: str, messages: list[ChatMessage]) -> ChatResult:
        started = time.monotonic()
        contents: list[dict[str, object]] = [
            {"role": _to_gemini_role(m.role), "parts": [{"text": m.content}]} for m in messages
        ]
        resp = await self._generate(api_key, model or DEFAULT_MODEL, contents)
        if resp.status_code >= 400:
            raise LlmProviderError(f"gemini chat failed: {resp.status_code} {resp.text}")
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata") or {}
        return ChatResult(
            content=text,
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
        )

    async def structured(self, *, api_key: str, model: str, messages: list[ChatMessage], schema: type[T]) -> T:
        result = await self.chat(api_key=api_key, model=model, messages=messages)
        try:
            return parse_structured(result.content, schema)
        except (json.JSONDecodeError, ValidationError) as e:
            repair_messages = build_repair_messages([m.model_dump() for m in messages], result.content, e, schema)
            retry_result = await self.chat(
                api_key=api_key, model=model, messages=[ChatMessage(**m) for m in repair_messages]
            )
            return parse_structured(retry_result.content, schema)

    async def probe_capabilities(self, *, api_key: str) -> LlmCapabilities:
        plain = await self._generate(api_key, DEFAULT_MODEL, [{"role": "user", "parts": [{"text": "ping"}]}])
        if plain.status_code >= 400:
            raise LlmProviderError(f"gemini probe failed: {plain.status_code} {plain.text}")
        json_resp = await self._generate(
            api_key,
            DEFAULT_MODEL,
            [{"role": "user", "parts": [{"text": "Return {}"}]}],
            generation_config={"responseMimeType": "application/json"},
        )
        return LlmCapabilities(
            json_mode=json_resp.status_code < 400,
            context_tokens=_CONTEXT_TOKENS,
            streaming=True,
        )
