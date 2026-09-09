"""Provider capability probe run on key connect/test (Roadmap Task 1 item 5;
API spec §3 `POST /settings/llm-keys/test`).
"""

from __future__ import annotations

import time

import httpx

from app.domain.user import LlmProvider, LlmTestResult
from app.llm.client import LlmProviderError
from app.llm.providers import gemini, openai_compat
from app.llm.providers.gemini import GeminiClient
from app.llm.providers.openai_compat import OpenAiCompatClient


def default_model_for(provider: LlmProvider) -> str:
    """The small default model each adapter uses for chat()/probe() calls
    when a caller doesn't need to pin a specific one (Roadmap Phase 3:
    profile extraction is the first caller)."""
    if provider == LlmProvider.GEMINI:
        return gemini.DEFAULT_MODEL
    return openai_compat.DEFAULT_MODELS[provider]


async def probe(provider: LlmProvider, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> LlmTestResult:
    started = time.monotonic()
    async with httpx.AsyncClient(transport=transport, timeout=15.0) as http_client:
        adapter = (
            GeminiClient(client=http_client)
            if provider == LlmProvider.GEMINI
            else OpenAiCompatClient(provider, client=http_client)
        )
        try:
            capabilities = await adapter.probe_capabilities(api_key=api_key)
        except LlmProviderError as e:
            return LlmTestResult(success=False, message=str(e))
    latency_ms = int((time.monotonic() - started) * 1000)
    return LlmTestResult(success=True, latency_ms=latency_ms, capabilities=capabilities)
