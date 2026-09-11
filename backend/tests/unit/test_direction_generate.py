from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.gap import GapEvidence, GapType, ResearchGap
from app.domain.profile import Confidence, SourceSpan
from app.domain.user import LlmProvider
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.directions.generate import generate_directions


def _session(payload: object | str, status: int = 200) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="err")
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 6, "completion_tokens": 4}})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="groq/x", provider=LlmProvider.GROQ,
    )


def _gap(**kw: object) -> ResearchGap:
    base: dict = {
        "gap_id": "gap_1",
        "workspace_id": "ws_1",
        "statement": "No workspace paper applies contrastive pretraining to dense retrieval.",
        "gap_type": GapType.METHOD_GAP,
        "supporting_papers": ["p1", "p2"],
        "supporting_evidence": [
            GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="we study dense retrieval")),
            GapEvidence(paper_id="p2", span=SourceSpan(paper_id="p2", quote="we also study dense retrieval")),
        ],
        "why_unaddressed": "The papers study dense retrieval but none adopt contrastive pretraining.",
        "proposed_direction": "Apply contrastive pretraining to the shared setting.",
        "affected_methods": ["contrastive pretraining"],
        "confidence": Confidence.MEDIUM,
        "self_support_passed": True,
        "user_state": "accepted",
    }
    base.update(kw)
    return ResearchGap(**base)


def test_no_session_yields_one_grounded_template_direction() -> None:
    res = asyncio.run(generate_directions(None, _gap(), max_directions=2))
    assert len(res.drafts) == 1
    d = res.drafts[0]
    assert d.kind == "evidence_backed_inference"
    assert d.generator_model is None
    assert "contrastive pretraining" in d.proposal


def test_llm_drafts_are_kept_when_grounded_and_classified_by_kind() -> None:
    payload = {
        "directions": [
            {
                "proposal": "Apply contrastive pretraining to the dense retrieval setting.",
                "motivation": "The papers study dense retrieval but do not adopt contrastive pretraining.",
                "suggested_method": "contrastive pretraining",
                "possible_dataset": None,
                "evaluation_strategy": "Evaluate on the shared dense retrieval setting.",
                "risks": ["May not transfer."],
            }
        ]
    }
    res = asyncio.run(generate_directions(_session(payload), _gap(), max_directions=2))
    assert len(res.drafts) == 1
    d = res.drafts[0]
    assert d.kind == "evidence_backed_inference"  # suggested_method already named by the gap
    assert d.generator_model == "groq/x"


def test_a_new_suggested_method_is_labelled_llm_hypothesis() -> None:
    payload = {
        "directions": [
            {
                "proposal": "Try graph neural retrieval on the dense retrieval setting.",
                "motivation": "The papers study dense retrieval but none adopt contrastive pretraining.",
                "suggested_method": "graph neural retrieval",
                "possible_dataset": None,
                "evaluation_strategy": "Evaluate recall.",
                "risks": ["Unproven."],
            }
        ]
    }
    res = asyncio.run(generate_directions(_session(payload), _gap(), max_directions=2))
    assert len(res.drafts) == 1
    assert res.drafts[0].kind == "llm_hypothesis"  # a genuinely new method, not in the gap's evidence


def test_a_draft_introducing_an_unsupported_claim_is_dropped() -> None:
    payload: dict = {
        "directions": [
            {
                "proposal": "Apply quantum annealing optimisation to the dense retrieval setting.",
                "motivation": "Prior work already demonstrated quantum annealing improves accuracy substantially.",
                "suggested_method": "quantum annealing optimisation",
                "possible_dataset": None,
                "evaluation_strategy": "Evaluate.",
                "risks": [],
            }
        ]
    }
    res = asyncio.run(generate_directions(_session(payload), _gap(), max_directions=2))
    assert res.drafts == []
    assert res.dropped_unsupported == 1


def test_multiple_directions_can_be_proposed_for_one_gap() -> None:
    payload = {
        "directions": [
            {"proposal": "Apply contrastive pretraining to dense retrieval.", "motivation": "The papers study dense retrieval but skip contrastive pretraining.", "suggested_method": "contrastive pretraining", "evaluation_strategy": "Evaluate.", "risks": []},
            {"proposal": "Combine dense retrieval with contrastive pretraining.", "motivation": "None of the dense retrieval papers try contrastive pretraining.", "suggested_method": "contrastive pretraining", "evaluation_strategy": "Evaluate.", "risks": []},
        ]
    }
    res = asyncio.run(generate_directions(_session(payload), _gap(), max_directions=2))
    assert len(res.drafts) == 2


def test_max_directions_caps_the_proposal_count() -> None:
    payload = {
        "directions": [
            {"proposal": "Apply contrastive pretraining to dense retrieval.", "motivation": "The papers study dense retrieval but skip contrastive pretraining.", "suggested_method": "contrastive pretraining", "evaluation_strategy": "Evaluate.", "risks": []},
            {"proposal": "Apply contrastive pretraining broadly to dense retrieval.", "motivation": "The papers study dense retrieval but skip contrastive pretraining.", "suggested_method": "contrastive pretraining", "evaluation_strategy": "Evaluate.", "risks": []},
            {"proposal": "Apply contrastive pretraining once more to dense retrieval.", "motivation": "The papers study dense retrieval but skip contrastive pretraining.", "suggested_method": "contrastive pretraining", "evaluation_strategy": "Evaluate.", "risks": []},
        ]
    }
    res = asyncio.run(generate_directions(_session(payload), _gap(), max_directions=1))
    assert len(res.drafts) == 1


def test_llm_failure_falls_back_to_the_template() -> None:
    res = asyncio.run(generate_directions(_session("not json"), _gap(), max_directions=2))
    assert len(res.drafts) == 1 and res.drafts[0].generator_model is None
