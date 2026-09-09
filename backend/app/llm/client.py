"""Provider-agnostic LLM client protocol (Architecture §7; Roadmap Task 1
item 5). Concrete adapters live in app/llm/providers/*. No business prompts
are sent in this phase -- chat()/structured() exist so later phases (P3+)
have a stable interface to build on ("no business prompts yet" per the
roadmap's stated Task 1 scope).
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.domain.user import LlmCapabilities

T = TypeVar("T", bound=BaseModel)


class LlmProviderError(Exception):
    """A provider call failed (maps to API spec 502 `provider_error`)."""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatResult(BaseModel):
    content: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    """Implemented by app/llm/providers/{openai_compat,gemini}.py."""

    async def chat(self, *, api_key: str, model: str, messages: list[ChatMessage]) -> ChatResult: ...

    async def structured(self, *, api_key: str, model: str, messages: list[ChatMessage], schema: type[T]) -> T: ...

    async def probe_capabilities(self, *, api_key: str) -> LlmCapabilities: ...
