"""Gemini adapter -- a different request/response shape from the
OpenAI-compatible family (Architecture §7). Uses the `x-goog-api-key`
header rather than Gemini's `?key=` query-parameter auth form, so the key
is never placed in a URL (never logged in access logs, never in a proxy's
URL-based cache key).

Failures, retries, JSON mode and usage follow the same contract as the
OpenAI-compatible adapter (app/llm/providers/openai_compat.py). `on_delta`
receives the whole reply at once: Gemini answers in one piece here.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable

import httpx
from pydantic import ValidationError

from app.domain.user import LlmCapabilities
from app.llm.client import ChatMessage, ChatResult, DeltaHook, LlmErrorKind, LlmProviderError, T
from app.llm.providers import openai_compat
from app.llm.providers.openai_compat import CONNECT_TIMEOUT_S, MAX_RETRIES, REQUEST_TIMEOUT_S
from app.llm.schema_repair import build_repair_messages, parse_structured

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-1.5-flash"
# Gemini 1.5 models advertise a 1M-token context window; see the openai_compat
# module docstring note on why this is a static, documented approximation
# rather than a live-queried value.
_CONTEXT_TOKENS = 1_000_000
_MAX_BACKOFF_S = 8.0


def _to_gemini_role(role: str) -> str:
    return "model" if role == "assistant" else "user"


def _error(message: str, kind: LlmErrorKind, status: int | None = None, detail: str | None = None) -> LlmProviderError:
    return LlmProviderError(message, kind=kind, status=status, provider="gemini", detail=detail)


def _error_from_response(resp: httpx.Response) -> LlmProviderError:
    status = resp.status_code
    detail = resp.text.strip()[:400]
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            detail = str(err.get("message") or detail)
    except (ValueError, AttributeError):
        pass
    if status in (401, 403) or "api key not valid" in detail.lower():
        kind = LlmErrorKind.AUTH
    elif status == 429:
        kind = LlmErrorKind.RATE_LIMITED
    elif status in (408, 504):
        kind = LlmErrorKind.TIMEOUT
    elif status >= 500:
        kind = LlmErrorKind.UNAVAILABLE
    else:
        kind = LlmErrorKind.BAD_REQUEST
    return _error(f"gemini answered {status}: {detail}", kind, status, detail)


class GeminiClient:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = REQUEST_TIMEOUT_S,
        max_retries: int = MAX_RETRIES,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client = client
        self._timeout = httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
        self._max_retries = max_retries
        self._sleep = sleep

    async def _generate(
        self, api_key: str, model: str, contents: list[dict[str, object]], generation_config: dict[str, object] | None = None
    ) -> httpx.Response:
        body: dict[str, object] = {"contents": contents}
        if generation_config:
            body["generationConfig"] = generation_config
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            return await client.post(
                f"{_BASE_URL}/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json=body,
            )
        except httpx.TimeoutException as e:
            raise _error(f"gemini didn't answer in time ({type(e).__name__})", LlmErrorKind.TIMEOUT) from e
        except httpx.TransportError as e:
            raise _error(f"couldn't reach gemini ({type(e).__name__})", LlmErrorKind.UNAVAILABLE) from e
        finally:
            if self._client is None:
                await client.aclose()

    async def _once(
        self, api_key: str, model: str, contents: list[dict[str, object]], json_mode: bool, temperature: float | None = None
    ) -> ChatResult:
        started = time.monotonic()
        config: dict[str, object] = {}
        if json_mode:
            config["responseMimeType"] = "application/json"
        if temperature is not None:
            config["temperature"] = temperature
        resp = await self._generate(api_key, model, contents, config or None)
        if resp.status_code >= 400:
            raise _error_from_response(resp)
        try:
            data = resp.json()
            candidate = data["candidates"][0]
            text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise _error("gemini sent a reply that isn't a completion", LlmErrorKind.BAD_RESPONSE) from e
        if not text.strip():
            raise _error("gemini sent an empty reply", LlmErrorKind.BAD_RESPONSE)
        usage = data.get("usageMetadata") or {}
        # Gemini counts a thinking model's thoughts apart from the reply
        # (candidatesTokenCount leaves them out); ChatResult's completion is both
        thoughts = int(usage.get("thoughtsTokenCount") or 0)
        return ChatResult(
            content=text,
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=int(usage.get("promptTokenCount") or 0),
            completion_tokens=int(usage.get("candidatesTokenCount") or 0) + thoughts,
            cached_prompt_tokens=int(usage.get("cachedContentTokenCount") or 0),
            reasoning_tokens=thoughts,
            model=data.get("modelVersion") if isinstance(data.get("modelVersion"), str) else None,
            finish_reason=candidate.get("finishReason"),
        )

    async def chat(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
        on_delta: DeltaHook | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        contents: list[dict[str, object]] = [
            {"role": _to_gemini_role(m.role), "parts": [{"text": m.content}]} for m in messages
        ]
        attempt = 0
        while True:
            try:
                result = await self._once(api_key, model or DEFAULT_MODEL, contents, json_mode, temperature)
                break
            except LlmProviderError as e:
                if not e.retryable or attempt >= self._max_retries:
                    raise
                attempt += 1
                await (self._sleep or openai_compat.backoff_sleep)(min(2.0 ** (attempt - 1), _MAX_BACKOFF_S))
        if on_delta is not None:
            on_delta(result.content)
        return result

    async def structured(self, *, api_key: str, model: str, messages: list[ChatMessage], schema: type[T]) -> T:
        result = await self.chat(api_key=api_key, model=model, messages=messages, json_mode=True)
        try:
            return parse_structured(result.content, schema)
        except (json.JSONDecodeError, ValidationError) as e:
            repair_messages = build_repair_messages([m.model_dump() for m in messages], result.content, e, schema)
            retry_result = await self.chat(
                api_key=api_key, model=model, messages=[ChatMessage(**m) for m in repair_messages], json_mode=True
            )
            return parse_structured(retry_result.content, schema)

    async def probe_capabilities(self, *, api_key: str) -> LlmCapabilities:
        plain = await self._generate(api_key, DEFAULT_MODEL, [{"role": "user", "parts": [{"text": "ping"}]}])
        if plain.status_code >= 400:
            raise _error_from_response(plain)
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
