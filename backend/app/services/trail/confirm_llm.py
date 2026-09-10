"""LLM confirmation of rule-fired relationships (Architecture §3 S11
`confirm_llm.py`). ONE structured call per candidate, batched over the
types the deterministic rules already proposed.

Hard constraints (Roadmap Phase 7: "The LLM must not invent evidence or
relationship types"):
- a `relationship_type` the LLM returns that was NOT in the proposed list
  is discarded;
- a `target_span` the LLM returns that cannot be found in the candidate's
  own abstract (verify_span) flips `confirmed` to False -- the LLM cannot
  invent evidence.

No session, a provider error, or malformed JSON -> `{}` (every rule stays
unconfirmed; the edge is still created from the rule alone, at capped
confidence -- see confidence.py).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from app.domain.trail import RelationshipType
from app.llm.client import ChatMessage, LlmProviderError
from app.llm.session import LlmSession
from app.services.trail.rules import CandidateView, RuleResult, TrailContext
from app.services.trail.verify_span import verify_quote_in_text

_CERTAINTIES = {"high", "medium", "low"}


class TrailConfirmation(BaseModel):
    confirmed: bool = False
    target_span: str | None = None
    certainty: str = "low"


class _LlmConfirmation(BaseModel):
    relationship_type: str
    confirmed: bool = False
    target_span: str | None = None
    certainty: str = "low"


class _LlmConfirmations(BaseModel):
    confirmations: list[_LlmConfirmation] = Field(default_factory=list)


_SYSTEM = (
    "You verify proposed relationships between a SEED paper and a CANDIDATE "
    "paper. For EACH proposed relationship_type, decide whether the "
    "candidate's own abstract supports it. Return JSON: {\"confirmations\": "
    "[{\"relationship_type\": <one of the proposed>, \"confirmed\": bool, "
    "\"target_span\": <a verbatim quote from the CANDIDATE abstract, or "
    "null>, \"certainty\": \"high\"|\"medium\"|\"low\"}]}. Never propose a "
    "type that was not given. Never quote text that is not in the abstract."
)


async def confirm_rule_results(
    session: LlmSession | None,
    ctx: TrailContext,
    cand: CandidateView,
    rule_results: list[RuleResult],
) -> dict[RelationshipType, TrailConfirmation]:
    proposed = [r.relationship_type for r in rule_results]
    if session is None or not proposed:
        return {}

    user = (
        f"SEED: {ctx.seed_title}\n{ctx.seed_abstract or ''}\n\n"
        f"CANDIDATE: {cand.title}\n{cand.abstract or ''}\n\n"
        f"Proposed relationship_types: {', '.join(t.value for t in proposed)}"
    )
    messages = [ChatMessage(role="system", content=_SYSTEM), ChatMessage(role="user", content=user)]
    try:
        result = await session.client.chat(api_key=session.api_key, model=session.model, messages=messages)
        parsed = _LlmConfirmations.model_validate_json(_extract_json(result.content))
    except (LlmProviderError, json.JSONDecodeError, ValidationError, ValueError):
        return {}

    abstract = cand.abstract or ""
    out: dict[RelationshipType, TrailConfirmation] = {}
    for item in parsed.confirmations:
        try:
            rtype = RelationshipType(item.relationship_type)
        except ValueError:
            continue
        if rtype not in proposed:  # LLM cannot introduce a new type
            continue
        span_ok = bool(item.target_span) and verify_quote_in_text(item.target_span or "", abstract)
        out[rtype] = TrailConfirmation(
            confirmed=bool(item.confirmed) and span_ok,
            target_span=item.target_span if span_ok else None,
            certainty=item.certainty if item.certainty in _CERTAINTIES else "low",
        )
    return out


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in response")
    return text[start : end + 1]
