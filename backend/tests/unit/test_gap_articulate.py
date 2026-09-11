from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.gap import GapEvidence, GapType
from app.domain.profile import SourceSpan
from app.domain.user import LlmProvider
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.gaps.articulate_llm import articulate, is_grounded
from app.services.gaps.candidates import GapCandidate


def _session(payload: object | str, status: int = 200) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="err")
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="groq/x", provider=LlmProvider.GROQ,
    )


def _candidate() -> GapCandidate:
    ev = [
        GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", section="Intro", char_start=1, char_end=9, quote="we study dense retrieval")),
        GapEvidence(paper_id="p2", span=SourceSpan(paper_id="p2", section="Intro", char_start=1, char_end=9, quote="we also study dense retrieval")),
    ]
    return GapCandidate(
        gap_type=GapType.METHOD_GAP,
        detection_rule="method_coverage",
        supporting_papers=["p1", "p2"],
        supporting_evidence=ev,
        affected_methods=["contrastive pretraining"],
        facts={"facet": "method", "value": "contrastive pretraining", "used_by": ["p3"], "missing_from": ["p1", "p2"]},
    )


def test_articulation_phrases_a_statement_from_the_facts_and_evidence() -> None:
    payload = {
        "statement": "No workspace paper applies contrastive pretraining to dense retrieval.",
        "why_unaddressed": "The papers study dense retrieval but do not use contrastive pretraining.",
        "proposed_direction": "Try contrastive pretraining on the shared setting.",
    }
    art = asyncio.run(articulate(_session(payload), _candidate()))
    assert art is not None
    assert "contrastive pretraining" in art.statement
    assert art.generator_model == "groq/x"


def test_adversarial_llm_that_adds_an_unsupported_method_is_caught() -> None:
    payload = {
        "statement": "No workspace paper applies quantum annealing to dense retrieval.",
        "why_unaddressed": "The papers ignore quantum annealing entirely.",
        "proposed_direction": "Use quantum annealing.",
    }
    art = asyncio.run(articulate(_session(payload), _candidate()))
    assert art is None  # 'quantum annealing' is not in the facts or evidence -> dropped


def test_is_grounded_helper_accepts_only_terms_present_in_facts_or_quotes() -> None:
    cand = _candidate()
    assert is_grounded("Papers study dense retrieval but skip contrastive pretraining.", "", cand) is True
    assert is_grounded("Papers should try reinforcement learning instead.", "", cand) is False


def test_no_session_falls_back_to_a_deterministic_template() -> None:
    art = asyncio.run(articulate(None, _candidate()))
    assert art is not None
    assert art.generator_model is None
    assert "contrastive pretraining" in art.statement
    # template is deterministic
    art2 = asyncio.run(articulate(None, _candidate()))
    assert art2 is not None
    assert (art.statement, art.why_unaddressed, art.proposed_direction) == (art2.statement, art2.why_unaddressed, art2.proposed_direction)


def test_llm_failure_falls_back_to_the_template_not_an_error() -> None:
    art = asyncio.run(articulate(_session("not json"), _candidate()))
    assert art is not None and art.generator_model is None
