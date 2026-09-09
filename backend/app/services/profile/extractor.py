"""Stage S4: the paper's first LLM call (Architecture §3 S4; Roadmap Phase
3). Deterministic input selection (context_selector.py) and deterministic
provenance resolution (provenance_check.py) surround this one call --
nothing else in Phase 3 talks to an LLM.

Orchestrates chat() + the schema-repair retry itself (rather than using
LLMClient.structured()) so both call attempts' token usage can be summed
onto the profile's `tokens` field (Data Model §2 `ResearchProfile.tokens`)
-- structured() intentionally doesn't expose that, only the parsed result.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.domain.chunk import PaperChunk
from app.domain.profile import TokenUsage
from app.llm.client import ChatMessage, LLMClient
from app.llm.prompts.profile_v1 import ProfileExtraction, build_profile_messages
from app.llm.schema_repair import build_repair_messages, parse_structured
from app.services.profile.context_selector import render_context, select_context_chunks


class ProfileExtractionFailed(Exception):
    """Raised when the LLM output could not be parsed as valid JSON matching
    ProfileExtraction, even after the one schema-repair retry (Data Model §2:
    "On any ValidationError after the single repair retry -> ..."). Callers
    must catch this and fall back to a partial profile -- never let it
    surface as a 500 (Roadmap Phase 3 Tests: "malformed-JSON never surfaces
    as a 500"). A genuine provider failure (LlmProviderError) is a different
    condition (API spec 502 `provider_error`) and is left to propagate
    uncaught."""


async def extract_profile(
    llm_client: LLMClient,
    *,
    api_key: str,
    model: str,
    chunks: list[PaperChunk],
    max_context_chars: int,
) -> tuple[ProfileExtraction, TokenUsage]:
    context_chunks = select_context_chunks(chunks, max_context_chars)
    messages = build_profile_messages(render_context(context_chunks))

    result = await llm_client.chat(api_key=api_key, model=model, messages=messages)
    tokens = TokenUsage(prompt=result.prompt_tokens, completion=result.completion_tokens)
    try:
        return parse_structured(result.content, ProfileExtraction), tokens
    except (json.JSONDecodeError, ValidationError) as e:
        repair_messages_raw = build_repair_messages(
            [m.model_dump() for m in messages], result.content, e, ProfileExtraction
        )
        retry_result = await llm_client.chat(
            api_key=api_key, model=model, messages=[ChatMessage(**m) for m in repair_messages_raw]
        )
        tokens = TokenUsage(
            prompt=tokens.prompt + retry_result.prompt_tokens,
            completion=tokens.completion + retry_result.completion_tokens,
        )
        try:
            return parse_structured(retry_result.content, ProfileExtraction), tokens
        except (json.JSONDecodeError, ValidationError) as e2:
            raise ProfileExtractionFailed(str(e2)) from e2
