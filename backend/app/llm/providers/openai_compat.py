"""OpenAI-compatible chat-completions adapter -- covers OpenAI, Groq,
DeepSeek, OpenRouter and Together, which all speak the same `/chat/
completions` shape (Architecture §7). Callers may inject an `httpx.
AsyncClient` (real or built on a `MockTransport`); when none is given, a
short-lived client is opened per call -- this keeps the capability probe
testable offline (Roadmap Task 1: "capability probe against a mocked
OpenAI-compatible endpoint") without any global network client at import
time.

What a call can rely on:
- every failure is one `LlmProviderError` with a `kind` (a rejected key, no
  credit, rate limiting, a timeout, an unavailable server, a refused
  request, an unreadable reply) -- transport errors and malformed bodies
  included, never a raw `httpx`/`KeyError`;
- rate limiting and server/connection failures are retried with backoff
  (honouring `Retry-After`); a rejected key or request is not;
- `json_mode` sends `response_format: json_object`, dropped once and for
  all on a provider that refuses it (as is DeepSeek's "don't think" flag);
- `on_delta` streams the reply over SSE (keep-alive comments skipped, the
  final usage chunk read), and still returns the whole `ChatResult`;
- usage is the provider's own count, including DeepSeek's cache hits and a
  thinking model's reasoning tokens;
- a model the provider no longer offers (DeepSeek renames its models) is
  replaced once by the provider's current equivalent from `GET /models`.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import ValidationError

from app.domain.user import LlmCapabilities, LlmProvider
from app.llm.client import ChatMessage, ChatResult, DeltaHook, LlmErrorKind, LlmProviderError, T
from app.llm.schema_repair import build_repair_messages, parse_structured

_BASE_URLS = {
    LlmProvider.OPENAI: "https://api.openai.com/v1",
    LlmProvider.GROQ: "https://api.groq.com/openai/v1",
    # DeepSeek's documented base URL (".../v1" is an alias of it)
    LlmProvider.DEEPSEEK: "https://api.deepseek.com",
    LlmProvider.OPENROUTER: "https://openrouter.ai/api/v1",
    LlmProvider.TOGETHER: "https://api.together.xyz/v1",
}

# A model must be named for the probe/chat calls; these are small, cheap
# defaults, not a business decision -- RESEARCHNEXUS_LLM_MODELS overrides
# them per provider (app/llm/session.py).
DEFAULT_MODELS = {
    LlmProvider.OPENAI: "gpt-4o-mini",
    LlmProvider.GROQ: "llama-3.1-8b-instant",
    # the fast model, asked not to think (_NO_THINKING); "deepseek-chat" is
    # only a legacy alias of that mode
    LlmProvider.DEEPSEEK: "deepseek-flash",
    LlmProvider.OPENROUTER: "openai/gpt-4o-mini",
    LlmProvider.TOGETHER: "meta-llama/Llama-3-8b-chat-hf",
}

# DeepSeek's models think before answering unless told not to: slower,
# billed as completion tokens, and no better at the short, grounded JSON
# every caller here asks for. Measured on one answer-verification call:
# 5,875 completion tokens and 25 s thinking, 13 tokens and 0.5 s without
# (the legacy "deepseek-chat" alias is exactly this non-thinking mode).
_NO_THINKING: dict[LlmProvider, dict[str, object]] = {
    LlmProvider.DEEPSEEK: {"thinking": {"type": "disabled"}},
}

# When a provider stops offering a model, the first of these it still
# offers takes its place. Only where the replacement is unambiguous.
_REPLACEMENTS = {
    LlmProvider.DEEPSEEK: ("deepseek-flash", "deepseek-chat"),
}

# Best-effort static context-window table for the MVP capability probe (API
# spec §3 `capabilities.context_tokens`). The OpenAI-compatible chat API has
# no endpoint that returns this live, so it is documented here as a known
# approximation rather than queried.
_CONTEXT_TOKENS = {
    LlmProvider.OPENAI: 128_000,
    LlmProvider.GROQ: 131_072,
    LlmProvider.DEEPSEEK: 128_000,
    LlmProvider.OPENROUTER: 128_000,
    LlmProvider.TOGETHER: 8_192,
}

# per read, not per call: a provider holding a busy request open sends
# keep-alive lines, and a streamed reply keeps arriving
REQUEST_TIMEOUT_S = 120.0
CONNECT_TIMEOUT_S = 10.0
MAX_RETRIES = 2
_MAX_BACKOFF_S = 8.0


async def backoff_sleep(seconds: float) -> None:
    """The wait between retries (a module function so tests can skip it)."""
    await asyncio.sleep(seconds)


def _usage(usage: object) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    cached = usage.get("prompt_cache_hit_tokens")  # DeepSeek
    if cached is None and isinstance(prompt_details, dict):
        cached = prompt_details.get("cached_tokens")  # OpenAI and most others
    reasoning = completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else None
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "cached_prompt_tokens": int(cached or 0),
        "reasoning_tokens": int(reasoning or 0),
    }


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class OpenAiCompatClient:
    # model replacements found at runtime, shared by every client of a provider
    _replaced: dict[tuple[LlmProvider, str], str] = {}

    def __init__(
        self,
        provider: LlmProvider,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = REQUEST_TIMEOUT_S,
        max_retries: int = MAX_RETRIES,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if provider not in _BASE_URLS:
            raise ValueError(f"{provider} is not an OpenAI-compatible provider")
        self._provider = provider
        self._client = client
        self._timeout = httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
        self._max_retries = max_retries
        self._sleep = sleep
        self._json_mode_supported = True
        self._stream_usage_supported = True
        self._no_thinking_supported = True

    # ------------------------------------------------------------------ errors

    def _error(
        self, message: str, kind: LlmErrorKind, status: int | None = None, retry_after: float | None = None, detail: str | None = None
    ) -> LlmProviderError:
        return LlmProviderError(
            message, kind=kind, status=status, provider=self._provider.value, retry_after_s=retry_after, detail=detail
        )

    def _error_from_response(self, resp: httpx.Response, body_text: str) -> LlmProviderError:
        status = resp.status_code
        detail, code = body_text.strip()[:400], ""
        try:
            payload = json.loads(body_text)
            err = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(err, dict):
                detail = str(err.get("message") or detail)
                code = f"{err.get('code') or ''} {err.get('type') or ''}".lower()
            elif isinstance(err, str):
                detail = err
        except ValueError:
            pass
        if status in (401, 403):
            kind = LlmErrorKind.AUTH
        elif status == 402 or "insufficient_quota" in code or "insufficient balance" in detail.lower():
            kind = LlmErrorKind.INSUFFICIENT_BALANCE
        elif status == 429:
            kind = LlmErrorKind.RATE_LIMITED
        elif status in (408, 504):
            kind = LlmErrorKind.TIMEOUT
        elif status >= 500:
            kind = LlmErrorKind.UNAVAILABLE
        else:
            kind = LlmErrorKind.BAD_REQUEST
        return self._error(f"{self._provider.value} answered {status}: {detail}", kind, status, _retry_after(resp), detail)

    # ------------------------------------------------------------------ transport

    async def _with_client(self, use: Callable[[httpx.AsyncClient], Awaitable[Any]]) -> Any:
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            return await use(client)
        except httpx.TimeoutException as e:
            raise self._error(f"{self._provider.value} didn't answer in time ({type(e).__name__})", LlmErrorKind.TIMEOUT) from e
        except httpx.TransportError as e:
            raise self._error(f"couldn't reach {self._provider.value} ({type(e).__name__})", LlmErrorKind.UNAVAILABLE) from e
        finally:
            if self._client is None:
                await client.aclose()

    def _url(self, path: str) -> str:
        return f"{_BASE_URLS[self._provider]}{path}"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    async def _post(self, api_key: str, body: dict[str, object]) -> httpx.Response:
        async def send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(self._url("/chat/completions"), headers=self._headers(api_key), json=body)

        resp: httpx.Response = await self._with_client(send)
        return resp

    # ------------------------------------------------------------------ one completion

    def _body(self, model: str, messages: list[ChatMessage], *, json_mode: bool, stream: bool) -> dict[str, object]:
        body: dict[str, object] = {"model": model, "messages": [m.model_dump() for m in messages]}
        if self._no_thinking_supported:
            body.update(_NO_THINKING.get(self._provider, {}))
        if json_mode and self._json_mode_supported:
            body["response_format"] = {"type": "json_object"}
        if stream:
            body["stream"] = True
            if self._stream_usage_supported:
                body["stream_options"] = {"include_usage": True}
        return body

    def _completion(self, data: object, started: float) -> ChatResult:
        if not isinstance(data, dict):
            raise self._error(f"{self._provider.value} sent a reply that isn't a completion", LlmErrorKind.BAD_RESPONSE)
        if data.get("error"):
            raise self._error(f"{self._provider.value} reported an error: {str(data['error'])[:300]}", LlmErrorKind.UNAVAILABLE)
        choices = data.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        message = choice.get("message") if choice else None
        content = message.get("content") if isinstance(message, dict) else None
        finish = choice.get("finish_reason") if choice else None
        if not isinstance(content, str) or not content.strip():
            raise self._error(
                f"{self._provider.value} sent an empty reply" + (f" (finish_reason: {finish})" if finish else ""),
                LlmErrorKind.BAD_RESPONSE,
            )
        return ChatResult(
            content=content,
            latency_ms=int((time.monotonic() - started) * 1000),
            model=data.get("model") if isinstance(data.get("model"), str) else None,
            finish_reason=finish if isinstance(finish, str) else None,
            **_usage(data.get("usage")),
        )

    async def _complete(self, api_key: str, body: dict[str, object], started: float) -> ChatResult:
        resp = await self._post(api_key, body)
        if resp.status_code >= 400:
            raise self._error_from_response(resp, resp.text)
        try:
            data = resp.json()
        except ValueError as e:
            raise self._error(f"{self._provider.value} sent a reply that isn't JSON", LlmErrorKind.BAD_RESPONSE) from e
        return self._completion(data, started)

    async def _stream(self, api_key: str, body: dict[str, object], started: float, on_delta: DeltaHook) -> ChatResult:
        async def read(client: httpx.AsyncClient) -> ChatResult:
            async with client.stream("POST", self._url("/chat/completions"), headers=self._headers(api_key), json=body) as resp:
                if resp.status_code >= 400:
                    raise self._error_from_response(resp, (await resp.aread()).decode(errors="replace"))
                if "text/event-stream" not in resp.headers.get("content-type", ""):
                    # the provider answered in one piece after all
                    try:
                        whole = self._completion(json.loads(await resp.aread()), started)
                    except ValueError as e:
                        raise self._error(f"{self._provider.value} sent a reply that isn't JSON", LlmErrorKind.BAD_RESPONSE) from e
                    on_delta(whole.content)
                    return whole
                parts: list[str] = []
                usage: dict[str, int] = {}
                model: str | None = None
                finish: str | None = None
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # blank separators and ": keep-alive" comments
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("error"):
                        raise self._error(
                            f"{self._provider.value} stopped mid-reply: {str(chunk['error'])[:300]}", LlmErrorKind.UNAVAILABLE
                        )
                    model = chunk.get("model") or model
                    usage = _usage(chunk.get("usage")) or usage
                    for choice in chunk.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            parts.append(delta)
                            on_delta(delta)
                        finish = choice.get("finish_reason") or finish
            content = "".join(parts)
            if not content.strip():
                raise self._error(
                    f"{self._provider.value} sent an empty reply" + (f" (finish_reason: {finish})" if finish else ""),
                    LlmErrorKind.BAD_RESPONSE,
                )
            return ChatResult(
                content=content, latency_ms=int((time.monotonic() - started) * 1000), model=model, finish_reason=finish, **usage
            )

        result: ChatResult = await self._with_client(read)
        return result

    async def _attempt(
        self, api_key: str, model: str, messages: list[ChatMessage], json_mode: bool, on_delta: DeltaHook | None
    ) -> ChatResult:
        """One logical request: optional features a provider refuses are
        dropped and the request sent again, once each."""
        started = time.monotonic()
        while True:
            body = self._body(model, messages, json_mode=json_mode, stream=on_delta is not None)
            try:
                if on_delta is None:
                    return await self._complete(api_key, body, started)
                return await self._stream(api_key, body, started, on_delta)
            except LlmProviderError as e:
                text = str(e).lower()
                if e.kind is not LlmErrorKind.BAD_REQUEST:
                    raise
                if "response_format" in body and ("response_format" in text or "json" in text):
                    self._json_mode_supported = False
                elif "thinking" in body and "thinking" in text:
                    self._no_thinking_supported = False
                elif "stream_options" in body and "stream_options" in text:
                    self._stream_usage_supported = False
                else:
                    raise

    async def _replacement_model(self, api_key: str, model: str) -> str | None:
        preferred = _REPLACEMENTS.get(self._provider)
        if not preferred:
            return None

        async def list_models(client: httpx.AsyncClient) -> httpx.Response:
            return await client.get(self._url("/models"), headers=self._headers(api_key))

        try:
            resp = await self._with_client(list_models)
            offered = [m.get("id") for m in resp.json().get("data", [])] if resp.status_code == 200 else []
        except (LlmProviderError, ValueError, AttributeError):
            return None
        return next((m for m in preferred if m in offered and m != model), None)

    async def chat(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
        on_delta: DeltaHook | None = None,
    ) -> ChatResult:
        model = self._replaced.get((self._provider, model), model)
        attempt = 0
        replaced = False
        while True:
            try:
                return await self._attempt(api_key, model, messages, json_mode, on_delta)
            except LlmProviderError as e:
                if e.kind is LlmErrorKind.BAD_REQUEST and not replaced and "model" in str(e).lower():
                    replaced = True
                    replacement = await self._replacement_model(api_key, model)
                    if replacement is not None:
                        self._replaced[(self._provider, model)] = replacement
                        model = replacement
                        continue
                if not e.retryable or attempt >= self._max_retries:
                    raise
                attempt += 1
                await (self._sleep or backoff_sleep)(min(e.retry_after_s or 2.0 ** (attempt - 1), _MAX_BACKOFF_S))

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
        model = self._replaced.get((self._provider, DEFAULT_MODELS[self._provider]), DEFAULT_MODELS[self._provider])
        no_thinking = _NO_THINKING.get(self._provider, {})
        plain = await self._post(
            api_key, {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5, **no_thinking}
        )
        if plain.status_code >= 400:
            raise self._error_from_response(plain, plain.text)
        json_mode_resp = await self._post(
            api_key,
            {
                "model": model,
                "messages": [{"role": "user", "content": "Return {} as JSON"}],
                "response_format": {"type": "json_object"},
                "max_tokens": 5,
                **no_thinking,
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
