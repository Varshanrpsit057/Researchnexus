"""Shared helpers for the RAG LLM stages (Roadmap Phase 9).

`chat_json` is the one place a RAG stage talks to the provider: it asks for
a JSON object (the provider's JSON mode where it has one) and returns the
parsed object, or `None` when no usable reply came. `temperature=0` is for
a judgement that must come out the same on every run (a DeepSeek verdict at
its default temperature of 1 flipped between runs of the same gap check). A reply that isn't the
requested JSON gets one repair request before giving up.

A provider failure (a rejected key, no credit, a timeout, ...) also returns
`None` by default -- every stage degrades on `None` -- unless the caller
passes `raise_provider_errors=True`: chat does, because an answer that
can't be generated at all should say why rather than "no usable answer".
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.llm.client import ChatMessage, LlmProviderError
from app.llm.session import LlmSession

_WS = re.compile(r"\s+")
_BRACKET_REF = re.compile(r"\s?\[\d+(?:\s?[-,]\s?\d+)*\]")
# A parenthetical that contains a 4-digit year and opens with a capital
# letter -- an author-year citation the LLM should not have written.
_PAREN_CITE = re.compile(r"\s?\((?=[^)]*\d{4}[a-z]?)[A-Z][^)]{0,60}?\)")
_REPAIR_ECHO_CHARS = 4000


def norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def contains_verbatim(haystack: str, needle: str) -> bool:
    """True when `needle` is (whitespace/case-insensitively) a literal span
    of `haystack`. Used to prove the LLM copied text rather than paraphrased."""
    n = norm(needle)
    return bool(n) and n in norm(haystack)


def strip_fabricated_references(text: str) -> str:
    """Remove `[1]` / `[1-3]` markers and `(Author, 2024)` parentheticals an
    LLM may inject -- reference strings come only from
    `services/citations/formatter.py`, never from generation."""
    cleaned = _PAREN_CITE.sub("", _BRACKET_REF.sub("", text))
    return _WS.sub(" ", cleaned).strip()


def extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in response")
    return text[start : end + 1]


async def chat_json(
    session: LlmSession | None,
    system: str,
    user: str,
    schema: type[BaseModel],
    *,
    raise_provider_errors: bool = False,
    temperature: float | None = None,
) -> tuple[BaseModel | None, int, int]:
    """Returns (parsed | None, prompt_tokens, completion_tokens) -- the
    tokens of every attempt, the repair included."""
    if session is None:
        return None, 0, 0
    messages = [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]
    pt = ct = 0
    for _attempt in range(2):
        try:
            result = await session.client.chat(
                api_key=session.api_key, model=session.model, messages=messages, json_mode=True, temperature=temperature
            )
        except LlmProviderError:
            if raise_provider_errors:
                raise
            return None, pt, ct
        pt += result.prompt_tokens
        ct += result.completion_tokens
        try:
            return schema.model_validate_json(extract_json(result.content)), pt, ct
        except ValueError as e:  # not JSON, or not the requested shape (pydantic's ValidationError is a ValueError)
            messages = [
                *messages,
                ChatMessage(role="assistant", content=result.content[:_REPAIR_ECHO_CHARS]),
                ChatMessage(
                    role="user",
                    content=f"That reply could not be used ({str(e)[:300]}). Reply again with only the JSON object, "
                    "in exactly the shape the instructions ask for.",
                ),
            ]
    return None, pt, ct
