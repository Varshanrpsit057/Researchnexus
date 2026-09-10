from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.candidate import CitationRelationship
from app.domain.profile import SourceSpan
from app.domain.ranking import SignalScores
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.trail.contradiction import verify_contradiction
from app.services.trail.rules import CandidateView


def _cand(abstract: str) -> CandidateView:
    return CandidateView(
        candidate_id="cand_1",
        paper_id="pap_x",
        title="A Contrarian Paper",
        abstract=abstract,
        year=2023,
        citation_relationship=CitationRelationship.NONE,
        citation_hops=None,
        signals=SignalScores(problem_sim=0.7),
    )


def _session(handler: httpx.MockTransport) -> LlmSession:
    from app.domain.user import LlmProvider

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=handler)),
        api_key="sk-x",
        model="m",
        provider=LlmProvider.GROQ,
    )


_SEED_CLAIM = "Retrieval-augmented generation reduces hallucination."
_SEED_SPAN = SourceSpan(paper_id="pap_seed", quote="Retrieval-augmented generation reduces hallucination.")


def test_contradiction_confirmed_with_a_span_from_both_papers() -> None:
    cand = _cand("We show retrieval does not reduce hallucination in long-form answers.")
    payload = {
        "contradiction": True,
        "seed_span": "Retrieval-augmented generation reduces hallucination.",
        "target_span": "retrieval does not reduce hallucination in long-form answers",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    pair = asyncio.run(verify_contradiction(_session(httpx.MockTransport(handler)), _SEED_CLAIM, _SEED_SPAN, cand))
    assert pair is not None
    roles = {e.role for e in pair}
    assert roles == {"seed_claim", "target_claim"}
    assert any(e.span.paper_id == "pap_seed" for e in pair)
    assert any(e.span.paper_id == "pap_x" for e in pair)


def test_no_edge_when_the_llm_says_no_contradiction() -> None:
    cand = _cand("We confirm retrieval reduces hallucination, echoing prior work.")
    payload = {"contradiction": False, "seed_span": None, "target_span": None}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    assert asyncio.run(verify_contradiction(_session(httpx.MockTransport(handler)), _SEED_CLAIM, _SEED_SPAN, cand)) is None


def test_no_edge_when_the_target_span_is_not_in_the_candidate_abstract() -> None:
    cand = _cand("An unrelated abstract about protein folding.")
    payload = {
        "contradiction": True,
        "seed_span": "Retrieval-augmented generation reduces hallucination.",
        "target_span": "retrieval does not reduce hallucination",  # not present in this abstract
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    assert asyncio.run(verify_contradiction(_session(httpx.MockTransport(handler)), _SEED_CLAIM, _SEED_SPAN, cand)) is None


def test_no_edge_when_the_seed_span_does_not_match_the_seed_claim() -> None:
    cand = _cand("We show retrieval does not reduce hallucination.")
    payload = {
        "contradiction": True,
        "seed_span": "the seed claims something entirely different",
        "target_span": "retrieval does not reduce hallucination",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    assert asyncio.run(verify_contradiction(_session(httpx.MockTransport(handler)), _SEED_CLAIM, _SEED_SPAN, cand)) is None


def test_no_edge_without_a_session_or_on_llm_failure() -> None:
    cand = _cand("We show retrieval does not reduce hallucination.")
    assert asyncio.run(verify_contradiction(None, _SEED_CLAIM, _SEED_SPAN, cand)) is None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    assert asyncio.run(verify_contradiction(_session(httpx.MockTransport(handler)), _SEED_CLAIM, _SEED_SPAN, cand)) is None
