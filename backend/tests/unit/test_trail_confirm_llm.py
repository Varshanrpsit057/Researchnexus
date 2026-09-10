from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.candidate import CitationRelationship
from app.domain.profile import Confidence
from app.domain.ranking import SignalScores as RankingSignals
from app.domain.trail import RelationshipType
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.trail.confirm_llm import confirm_rule_results
from app.services.trail.rules import CandidateView, RuleResult, TrailContext


def _ctx() -> TrailContext:
    return TrailContext(
        seed_paper_id="pap_seed",
        seed_year=2020,
        seed_title="Retrieval-Augmented Generation",
        seed_abstract="We combine parametric and non-parametric memory.",
        seed_datasets=[],
        seed_methods=["dense retrieval"],
        seed_findings=[],
    )


def _cand() -> CandidateView:
    return CandidateView(
        candidate_id="cand_1",
        paper_id="pap_x",
        title="Fusion-in-Decoder",
        abstract="We extend retrieval-augmented models with a fusion-in-decoder reader for open-domain QA.",
        year=2021,
        citation_relationship=CitationRelationship.CITES_SEED,
        citation_hops=1,
        signals=RankingSignals(method_sim=0.7, problem_sim=0.6),
    )


def _rule(rt: RelationshipType) -> RuleResult:
    return RuleResult(relationship_type=rt, rule_fired="x", evidence=[], rule_confidence=Confidence.MEDIUM, signal_agreement=1)


def _session(handler: httpx.MockTransport) -> LlmSession:
    from app.domain.user import LlmProvider

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=handler)),
        api_key="sk-x",
        model="m",
        provider=LlmProvider.GROQ,
    )


def test_confirmation_marks_a_type_confirmed_and_verifies_its_span() -> None:
    payload = {
        "confirmations": [
            {
                "relationship_type": "METHOD_EXTENSION",
                "confirmed": True,
                "target_span": "fusion-in-decoder reader for open-domain QA",
                "certainty": "high",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    out = asyncio.run(
        confirm_rule_results(_session(httpx.MockTransport(handler)), _ctx(), _cand(), [_rule(RelationshipType.METHOD_EXTENSION)])
    )
    c = out[RelationshipType.METHOD_EXTENSION]
    assert c.confirmed is True
    assert c.certainty == "high"
    assert c.target_span == "fusion-in-decoder reader for open-domain QA"


def test_a_confirmed_span_not_present_in_the_abstract_is_treated_as_unconfirmed() -> None:
    payload = {
        "confirmations": [
            {"relationship_type": "METHOD_EXTENSION", "confirmed": True, "target_span": "this paper wins ImageNet", "certainty": "high"}
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    out = asyncio.run(
        confirm_rule_results(_session(httpx.MockTransport(handler)), _ctx(), _cand(), [_rule(RelationshipType.METHOD_EXTENSION)])
    )
    assert out[RelationshipType.METHOD_EXTENSION].confirmed is False  # span invented -> rejected


def test_llm_cannot_introduce_a_type_that_was_not_proposed() -> None:
    payload = {
        "confirmations": [
            {"relationship_type": "POTENTIALLY_CONTRADICTORY", "confirmed": True, "target_span": "open-domain QA", "certainty": "high"},
            {"relationship_type": "METHOD_EXTENSION", "confirmed": True, "target_span": "open-domain QA", "certainty": "medium"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    out = asyncio.run(
        confirm_rule_results(_session(httpx.MockTransport(handler)), _ctx(), _cand(), [_rule(RelationshipType.METHOD_EXTENSION)])
    )
    assert set(out) == {RelationshipType.METHOD_EXTENSION}  # the unsolicited type is dropped


def test_no_session_returns_no_confirmations() -> None:
    out = asyncio.run(confirm_rule_results(None, _ctx(), _cand(), [_rule(RelationshipType.SIMILAR)]))
    assert out == {}


def test_llm_failure_returns_no_confirmations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    out = asyncio.run(
        confirm_rule_results(_session(httpx.MockTransport(handler)), _ctx(), _cand(), [_rule(RelationshipType.SIMILAR)])
    )
    assert out == {}


def test_malformed_llm_json_returns_no_confirmations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    out = asyncio.run(
        confirm_rule_results(_session(httpx.MockTransport(handler)), _ctx(), _cand(), [_rule(RelationshipType.SIMILAR)])
    )
    assert out == {}
