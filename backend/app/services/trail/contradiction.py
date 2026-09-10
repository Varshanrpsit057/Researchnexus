"""Contradiction verification for `POTENTIALLY_CONTRADICTORY` (Architecture
§3 S11 `contradiction.py`). An NLI-style call per (seed key-claim,
candidate) pair.

An edge is created ONLY if the LLM says `contradiction: true` AND a
quotable span is verified in BOTH papers (Data Model §5: "never created
without a quotable span from both papers"; Architecture S11 failure
handling: "no quotable span from both -> do not create the edge"). No
session or any LLM failure -> no edge (the conservative, high-precision
default).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from app.domain.profile import SourceSpan
from app.domain.trail import Evidence
from app.llm.client import ChatMessage, LlmProviderError
from app.llm.session import LlmSession
from app.services.trail.rules import CandidateView
from app.services.trail.verify_span import find_span, verify_quote_in_text

_SYSTEM = (
    "You are a scientific NLI checker. Given a SEED claim and a CANDIDATE "
    "abstract, decide whether the candidate CONTRADICTS the seed claim "
    "(states the opposite finding on the same question). Return JSON: "
    "{\"contradiction\": bool, \"seed_span\": <verbatim substring of the "
    "SEED claim>, \"target_span\": <verbatim substring of the CANDIDATE "
    "abstract>}. Both spans are required when contradiction is true; quote "
    "text exactly."
)


class _NliResult(BaseModel):
    contradiction: bool = False
    seed_span: str | None = None
    target_span: str | None = None


async def verify_contradiction(
    session: LlmSession | None,
    seed_claim_text: str,
    seed_claim_span: SourceSpan | None,
    cand: CandidateView,
) -> tuple[Evidence, Evidence] | None:
    if session is None or not seed_claim_text.strip():
        return None

    user = f"SEED claim: {seed_claim_text}\n\nCANDIDATE abstract: {cand.title}\n{cand.abstract or ''}"
    messages = [ChatMessage(role="system", content=_SYSTEM), ChatMessage(role="user", content=user)]
    try:
        result = await session.client.chat(api_key=session.api_key, model=session.model, messages=messages)
        nli = _NliResult.model_validate_json(_extract_json(result.content))
    except (LlmProviderError, json.JSONDecodeError, ValidationError, ValueError):
        return None

    if not nli.contradiction or not nli.seed_span or not nli.target_span:
        return None

    if not verify_quote_in_text(nli.seed_span, seed_claim_text):
        return None
    target_span = find_span(nli.target_span, cand.abstract or "", paper_id=cand.paper_id)
    if target_span is None:
        return None

    seed_span = (
        seed_claim_span
        if seed_claim_span is not None
        else SourceSpan(paper_id="", quote=nli.seed_span[:400])
    )
    return (
        Evidence(span=seed_span, role="seed_claim"),
        Evidence(span=target_span, role="target_claim"),
    )


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in response")
    return text[start : end + 1]
