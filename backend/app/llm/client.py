"""Provider-agnostic LLM client protocol (Architecture §7; Roadmap Task 1
item 5). Concrete adapters live in app/llm/providers/*.

Every adapter reports failures as one `LlmProviderError` whose `kind` says
what went wrong in terms a caller can act on (a rejected key is not a busy
server), and every successful call reports the provider's own token usage
(`ChatResult`) -- the numbers the usage ledger (app/llm/usage.py) records.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import Enum
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.domain.user import LlmCapabilities

T = TypeVar("T", bound=BaseModel)

# a delta of streamed reply text, as it arrives
DeltaHook = Callable[[str], None]


class LlmErrorKind(str, Enum):
    AUTH = "auth"  # the key was rejected (401/403)
    INSUFFICIENT_BALANCE = "insufficient_balance"  # the account has no credit (402)
    RATE_LIMITED = "rate_limited"  # 429
    TIMEOUT = "timeout"  # no answer in time
    UNAVAILABLE = "unavailable"  # 5xx, overloaded, or the connection failed
    BAD_REQUEST = "bad_request"  # the provider refused the request (400/404/422: e.g. an unknown model)
    BAD_RESPONSE = "bad_response"  # a reply that isn't a readable completion


_RETRYABLE = {LlmErrorKind.RATE_LIMITED, LlmErrorKind.UNAVAILABLE}
_SECRET = re.compile(r"(sk-|AIza)[A-Za-z0-9_\-]{6,}")


def redact(text: str) -> str:
    """Providers sometimes echo (part of) a key in an error; never pass one on."""
    return _SECRET.sub("[redacted]", text)


class LlmProviderError(Exception):
    """A provider call failed (maps to API spec 502 `provider_error`)."""

    def __init__(
        self,
        message: str,
        *,
        kind: LlmErrorKind = LlmErrorKind.UNAVAILABLE,
        status: int | None = None,
        provider: str | None = None,
        retry_after_s: float | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(redact(message))
        self.kind = kind
        self.status = status
        self.provider = provider
        self.retry_after_s = retry_after_s
        # the provider's own explanation, when it gave one
        self.detail = redact(detail) if detail else None

    @property
    def retryable(self) -> bool:
        return self.kind in _RETRYABLE


PROVIDER_NAMES = {
    "openai": "OpenAI",
    "groq": "Groq",
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "together": "Together",
    "gemini": "Gemini",
}


def describe_provider_error(error: LlmProviderError) -> str:
    """What went wrong, for the person who asked, with what they can do."""
    name = PROVIDER_NAMES.get(error.provider or "", "The language model provider")
    kind = error.kind
    if kind is LlmErrorKind.AUTH:
        return f"{name} rejected the saved API key. Check it in Settings, or save a new one."
    if kind is LlmErrorKind.INSUFFICIENT_BALANCE:
        return f"Your {name} account is out of credit. Top it up, then try again."
    if kind is LlmErrorKind.RATE_LIMITED:
        return f"{name} is limiting requests right now. Wait a moment, then try again."
    if kind is LlmErrorKind.TIMEOUT:
        return f"{name} took too long to answer. Try again in a moment."
    if kind is LlmErrorKind.BAD_REQUEST:
        detail = f" ({error.detail[:200].rstrip('.')})" if error.detail else ""
        return f"{name} refused the request{detail}."
    if kind is LlmErrorKind.BAD_RESPONSE:
        return f"{name} sent a reply that couldn't be read. Try again."
    return f"{name} is unavailable right now. Try again in a moment."


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatResult(BaseModel):
    content: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # the prompt tokens the provider served from its cache (billed lower)
    cached_prompt_tokens: int = 0
    # hidden reasoning tokens a thinking model spent (billed as completion)
    reasoning_tokens: int = 0
    # the model that actually answered (a provider may resolve an alias)
    model: str | None = None
    finish_reason: str | None = None


class LLMClient(Protocol):
    """Implemented by app/llm/providers/{openai_compat,gemini}.py.

    `json_mode` asks the provider for a JSON object when it supports that;
    `on_delta` streams the reply, calling it with each piece of text as it
    arrives -- either way the full `ChatResult` (with usage) is returned.
    `temperature` overrides the provider's default sampling (0 for a
    judgement that should come out the same every time)."""

    async def chat(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
        on_delta: DeltaHook | None = None,
        temperature: float | None = None,
    ) -> ChatResult: ...

    async def structured(self, *, api_key: str, model: str, messages: list[ChatMessage], schema: type[T]) -> T: ...

    async def probe_capabilities(self, *, api_key: str) -> LlmCapabilities: ...
