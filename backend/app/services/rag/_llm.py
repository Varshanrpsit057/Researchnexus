"""Shared helpers for the RAG LLM stages (Roadmap Phase 9).

`chat_json` is the one place a RAG stage talks to the provider: it runs a
single BYOK chat call and returns the parsed object, or `None` on any
failure (no session / provider error / non-JSON / schema mismatch). Every
stage degrades on `None` -- the pipeline never raises because the LLM
misbehaved.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ValidationError

from app.llm.client import ChatMessage, LlmProviderError
from app.llm.session import LlmSession

_WS = re.compile(r"\s+")
_BRACKET_REF = re.compile(r"\s?\[\d+(?:\s?[-,]\s?\d+)*\]")
# A parenthetical that contains a 4-digit year and opens with a capital
# letter -- an author-year citation the LLM should not have written.
_PAREN_CITE = re.compile(r"\s?\((?=[^)]*\d{4}[a-z]?)[A-Z][^)]{0,60}?\)")


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
) -> tuple[BaseModel | None, int, int]:
    """Returns (parsed | None, prompt_tokens, completion_tokens)."""
    if session is None:
        return None, 0, 0
    messages = [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]
    try:
        result = await session.client.chat(api_key=session.api_key, model=session.model, messages=messages)
    except LlmProviderError:
        return None, 0, 0
    try:
        parsed = schema.model_validate_json(extract_json(result.content))
    except (json.JSONDecodeError, ValidationError, ValueError):
        return None, result.prompt_tokens, result.completion_tokens
    return parsed, result.prompt_tokens, result.completion_tokens
