from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.gap import GapEvidence, GapType
from app.domain.profile import Confidence, SourceSpan
from app.domain.user import LlmProvider
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.gaps.candidates import GapCandidate
from app.services.gaps.confidence import assign_confidence, self_support_check


def _session(supported: bool, status: int = 200) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="err")
        payload = {"results": [{"index": 0, "supported": supported}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="m", provider=LlmProvider.GROQ,
    )


def _cand(n: int, *, gap_type: GapType = GapType.METHOD_GAP, limitation_agreement: bool = False) -> GapCandidate:
    papers = [f"p{i}" for i in range(n)]
    ev = [GapEvidence(paper_id=p, span=SourceSpan(paper_id=p, quote=f"q{p}")) for p in papers]
    facts: dict = {"limitation_agreement": True} if limitation_agreement else {}
    return GapCandidate(gap_type=gap_type, detection_rule="r", supporting_papers=papers, supporting_evidence=ev, facts=facts)


def test_self_support_check_uses_the_isupported_verifier() -> None:
    assert asyncio.run(self_support_check(_session(True), "the gap statement", ["evidence a", "evidence b"])) is True
    assert asyncio.run(self_support_check(_session(False), "the gap statement", ["evidence a"])) is False


def test_self_support_is_false_without_a_session_or_evidence_or_on_failure() -> None:
    assert asyncio.run(self_support_check(None, "s", ["q"])) is False
    assert asyncio.run(self_support_check(_session(True), "s", [])) is False
    assert asyncio.run(self_support_check(_session(True, status=500), "s", ["q"])) is False


def test_failed_self_support_yields_low_and_records_the_basis() -> None:
    band, basis = assign_confidence(_cand(3, limitation_agreement=True), self_support_passed=False, evidence_coverage=1.0)
    assert band is Confidence.LOW
    assert basis["self_support"] is False and basis["n_supporting"] == 3


def test_confidence_band_derives_only_from_the_basis() -> None:
    high, _ = assign_confidence(_cand(3, limitation_agreement=True), self_support_passed=True, evidence_coverage=0.9)
    assert high is Confidence.HIGH
    med, _ = assign_confidence(_cand(2), self_support_passed=True, evidence_coverage=0.5)
    assert med is Confidence.MEDIUM
    low, _ = assign_confidence(_cand(2), self_support_passed=True, evidence_coverage=0.1)
    assert low is Confidence.LOW


def test_confidence_is_an_enum_band_never_a_percentage() -> None:
    band, basis = assign_confidence(_cand(2), self_support_passed=True, evidence_coverage=0.5)
    assert band.value in {"high", "medium", "low"}
    assert "%" not in json.dumps(basis)
    assert all(not isinstance(v, float) or 0.0 <= v <= 1.0 for v in basis.values() if isinstance(v, float))


def test_contradiction_counts_as_strong_support_for_the_high_band() -> None:
    band, _ = assign_confidence(_cand(3, gap_type=GapType.CONTRADICTION), self_support_passed=True, evidence_coverage=0.7)
    assert band is Confidence.HIGH
