from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.user import LlmProvider
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.directions.critique import critique_direction
from app.services.directions.generate import DirectionDraft


def _session(payload: object | str, status: int = 200) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="err")
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="m", provider=LlmProvider.GROQ,
    )


def _draft(**kw: object) -> DirectionDraft:
    base: dict = {
        "proposal": "Apply contrastive pretraining.", "motivation": "The gap shows it is missing.",
        "suggested_method": "contrastive pretraining", "possible_dataset": None,
        "evaluation_strategy": "Evaluate.", "risks": ["r"], "kind": "evidence_backed_inference",
        "generator_model": "m",
    }
    base.update(kw)
    return DirectionDraft(**base)


def test_llm_critique_scores_are_returned_and_clamped() -> None:
    scores, pt, ct = asyncio.run(critique_direction(_session({"novelty": 9, "specificity": 0, "feasibility": 5, "groundedness": 4}), _draft()))
    assert scores == {"novelty": 5, "specificity": 1, "feasibility": 5, "groundedness": 4}  # clamped to [1,5]; ResearchDirection caps feasibility later


def test_no_session_uses_a_conservative_deterministic_fallback() -> None:
    scores, pt, ct = asyncio.run(critique_direction(None, _draft(kind="evidence_backed_inference")))
    assert scores["groundedness"] >= 4  # evidence-backed -> can claim strong groundedness
    assert scores["feasibility"] <= 2   # feasibility stays conservative
    assert (pt, ct) == (0, 0)


def test_fallback_is_less_confident_for_an_llm_hypothesis() -> None:
    inferred, _, _ = asyncio.run(critique_direction(None, _draft(kind="evidence_backed_inference")))
    hypothesis, _, _ = asyncio.run(critique_direction(None, _draft(kind="llm_hypothesis")))
    assert hypothesis["groundedness"] < inferred["groundedness"]


def test_llm_failure_falls_back_deterministically() -> None:
    scores, _, _ = asyncio.run(critique_direction(_session("not json"), _draft()))
    assert set(scores) == {"novelty", "specificity", "feasibility", "groundedness"}
    assert all(1 <= v <= 5 for v in scores.values())
