from __future__ import annotations

import json

from app.domain.gap import GapEvidence, GapType, ResearchGap
from app.domain.profile import Confidence, SourceSpan
from app.services.directions.confidence import assign_confidence


def _gap(**kw: object) -> ResearchGap:
    base: dict = {
        "gap_id": "gap_1", "workspace_id": "ws_1", "statement": "s", "gap_type": GapType.METHOD_GAP,
        "supporting_papers": ["p1", "p2"],
        "supporting_evidence": [GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="q"))],
        "confidence": Confidence.MEDIUM, "self_support_passed": True, "user_state": "accepted",
    }
    base.update(kw)
    return ResearchGap(**base)


def test_high_requires_evidence_backed_kind_strong_critique_and_gap_confidence() -> None:
    band, basis = assign_confidence(
        "evidence_backed_inference", {"novelty": 2, "specificity": 4, "feasibility": 2, "groundedness": 5}, _gap()
    )
    assert band is Confidence.HIGH
    assert basis["kind"] == "evidence_backed_inference"


def test_llm_hypothesis_cannot_reach_high_even_with_strong_critique() -> None:
    band, _ = assign_confidence(
        "llm_hypothesis", {"novelty": 4, "specificity": 5, "feasibility": 2, "groundedness": 5}, _gap()
    )
    assert band is not Confidence.HIGH


def test_medium_band_for_moderate_critique() -> None:
    band, _ = assign_confidence(
        "llm_hypothesis", {"novelty": 3, "specificity": 2, "feasibility": 2, "groundedness": 3}, _gap()
    )
    assert band is Confidence.MEDIUM


def test_low_band_for_weak_critique() -> None:
    band, basis = assign_confidence(
        "llm_hypothesis", {"novelty": 2, "specificity": 1, "feasibility": 1, "groundedness": 1}, _gap()
    )
    assert band is Confidence.LOW
    assert basis["low_critique"] is True


def test_an_unsupported_gap_forces_low_regardless_of_critique() -> None:
    band, basis = assign_confidence(
        "evidence_backed_inference", {"novelty": 5, "specificity": 5, "feasibility": 3, "groundedness": 5},
        _gap(self_support_passed=False),
    )
    assert band is Confidence.LOW
    assert basis["gap_self_support"] is False


def test_confidence_is_an_enum_band_never_a_percentage() -> None:
    band, basis = assign_confidence(
        "evidence_backed_inference", {"novelty": 3, "specificity": 3, "feasibility": 2, "groundedness": 4}, _gap()
    )
    assert band.value in {"high", "medium", "low"}
    assert "%" not in json.dumps(basis)
