"""LLM critique pass (Architecture §4 `DirectionGenerator`: "LLM generate
-> LLM critique"; Roadmap Phase 12).

Scores a drafted direction 1-5 on novelty / specificity / feasibility /
groundedness. `feasibility` is deliberately treated as uncertain (Si et
al., "LLM ideas over-novel / infeasible") -- the domain model caps it at 3
regardless of what the LLM (or the deterministic fallback) returns. No
session / malformed output / provider failure -> a deterministic,
conservative critique that never claims high groundedness for a direction
it could not actually check.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.llm.session import LlmSession
from app.services.directions.generate import DirectionDraft
from app.services.rag._llm import chat_json

_KEYS = ("novelty", "specificity", "feasibility", "groundedness")

_SYSTEM = (
    "Rate the DIRECTION on 4 axes, each an integer 1-5: novelty (is it a fresh "
    "idea?), specificity (is it concrete and actionable?), feasibility (how "
    "practical -- be conservative and uncertain), groundedness (how well does "
    "the motivation follow from the GAP evidence?). Return JSON: "
    '{"novelty":<1-5>,"specificity":<1-5>,"feasibility":<1-5>,"groundedness":<1-5>}.'
)


class _CritiqueOut(BaseModel):
    novelty: int = 3
    specificity: int = 3
    feasibility: int = 2
    groundedness: int = 3


def _fallback(draft: DirectionDraft) -> dict:
    evidence_backed = draft.kind == "evidence_backed_inference"
    return {
        "novelty": 2 if evidence_backed else 3,
        "specificity": 3 if draft.suggested_method else 2,
        "feasibility": 2,
        "groundedness": 4 if evidence_backed else 2,
    }


async def critique_direction(
    session: LlmSession | None, draft: DirectionDraft
) -> tuple[dict, int, int]:
    if session is None:
        return _fallback(draft), 0, 0

    user = (
        f"GAP-DERIVED DIRECTION\nproposal: {draft.proposal}\nmotivation: {draft.motivation}\n"
        f"suggested_method: {draft.suggested_method}\npossible_dataset: {draft.possible_dataset}\n"
        f"evaluation_strategy: {draft.evaluation_strategy}\nkind: {draft.kind}"
    )
    parsed, pt, ct = await chat_json(session, _SYSTEM, user, _CritiqueOut)
    if parsed is None:
        return _fallback(draft), pt, ct
    assert isinstance(parsed, _CritiqueOut)
    scores = {k: max(1, min(5, int(getattr(parsed, k)))) for k in _KEYS}
    return scores, pt, ct
