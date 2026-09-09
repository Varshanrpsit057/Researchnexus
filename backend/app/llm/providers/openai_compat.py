"""OpenAI-compatible chat-completions adapter -- covers OpenAI, Groq,
DeepSeek, OpenRouter and Together, which all speak the same `/chat/
completions` shape (Architecture §7). Callers may inject an `httpx.
AsyncClient` (real or built on a `MockTransport`); when none is given, a
short-lived client is opened per call -- this keeps the capability probe
testable offline (Roadmap Task 1: "capability probe against a mocked
OpenAI-compatible endpoint") without any global network client at import
time.
"""

from __future__ import annotations

import json
import time

import httpx
from pydantic import ValidationError

from app.domain.user import LlmCapabilities, LlmProvider
from app.llm.client import ChatMessage, ChatResult, LlmProviderError, T
from app.llm.schema_repair import build_repair_messages, parse_structured

_BASE_URLS = {
    LlmProvider.OPENAI: "https://api.openai.com/v1",
    LlmProvider.GROQ: "https://api.groq.com/openai/v1",
    LlmProvider.DEEPSEEK: "https://api.deepseek.com/v1",
    LlmProvider.OPENROUTER: "https://openrouter.ai/api/v1",
    LlmProvider.TOGETHER: "https://api.together.xyz/v1",
}

# A model must be named for the probe/chat calls; these are small, cheap
# defaults, not a business decision -- callers of chat()/structured() in
# later phases pass their own `model`.
DEFAULT_MODELS = {
    LlmProvider.OPENAI: "gpt-4o-mini",
    LlmProvider.GROQ: "llama-3.1-8b-instant",
    LlmProvider.DEEPSEEK: "deepseek-chat",
    LlmProvider.OPENROUTER: "openai/gpt-4o-mini",
    LlmProvider.TOGETHER: "meta-llama/Llama-3-8b-chat-hf",
}

# Best-effort static context-window table for the MVP capability probe (API
# spec §3 `capabilities.context_tokens`). The OpenAI-compatible chat API has
# no endpoint that returns this live, so it is documented here as a known
# approximation rather than queried.
_CONTEXT_TOKENS = {
    LlmProvider.OPENAI: 128_000,
    LlmProvider.GROQ: 131_072,
    LlmProvider.DEEPSEEK: 64_000,
    LlmProvider.OPENROUTER: 128_000,
    LlmProvider.TOGETHER: 8_192,
}


class OpenAiCompatClient:
    def __init__(self, provider: LlmProvider, *, client: httpx.AsyncClient | None = None) -> None:
        if provider not in _BASE_URLS:
            raise ValueError(f"{provider} is not an OpenAI-compatible provider")
        self._provider = provider
        self._client = client

    async def _post(self, api_key: str, body: dict[str, object]) -> httpx.Response:
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            return await client.post(
                f"{_BASE_URLS[self._provider]}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def chat(self, *, api_key: str, model: str, messages: list[ChatMessage]) -> ChatResult:
        started = time.monotonic()
        resp = await self._post(api_key, {"model": model, "messages": [m.model_dump() for m in messages]})
        if resp.status_code >= 400:
            raise LlmProviderError(f"{self._provider.value} chat failed: {resp.status_code} {resp.text}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        return ChatResult(
            content=content,
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
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
        model = DEFAULT_MODELS[self._provider]
        plain = await self._post(api_key, {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5})
        if plain.status_code >= 400:
            raise LlmProviderError(f"{self._provider.value} probe failed: {plain.status_code} {plain.text}")
        json_mode_resp = await self._post(
            api_key,
            {
                "model": model,
                "messages": [{"role": "user", "content": "Return {}"}],
                "response_format": {"type": "json_object"},
                "max_tokens": 5,
            },
        )
        return LlmCapabilities(
            json_mode=json_mode_resp.status_code < 400,
            context_tokens=_CONTEXT_TOKENS.get(self._provider, 8_192),
            # OpenAI-compatible chat/completions always supports `stream:
            # true` SSE per the spec these providers implement; not probed
            # live to avoid a second round-trip for a fixed protocol fact.
            streaming=True,
        )
