from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.gap import GapEvidence, GapType, GapUserState, ResearchGap
from app.domain.profile import Confidence, SourceSpan


def _gap(**kw: object) -> ResearchGap:
    base: dict = {
        "gap_id": "gap_1",
        "workspace_id": "ws_1",
        "statement": "No workspace paper applies X to problem Y.",
        "gap_type": GapType.METHOD_GAP,
        "supporting_papers": ["p1", "p2"],
        "supporting_evidence": [
            GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="we study Y")),
            GapEvidence(paper_id="p2", span=SourceSpan(paper_id="p2", quote="we also study Y")),
        ],
    }
    base.update(kw)
    return ResearchGap(**base)


def test_gap_type_enum_has_the_nine_data_model_values() -> None:
    assert {t.value for t in GapType} == {
        "METHOD_GAP", "DATASET_GAP", "EVALUATION_GAP", "DOMAIN_GAP", "PERFORMANCE_GAP",
        "GENERALIZATION_GAP", "CONTRADICTION", "UNEXPLORED_COMBINATION", "TEMPORAL_GAP",
    }


def test_requires_at_least_two_distinct_supporting_papers() -> None:
    with pytest.raises(ValidationError):
        _gap(supporting_papers=["p1"])
    with pytest.raises(ValidationError):
        _gap(supporting_papers=["p1", "p1"])


def test_requires_at_least_one_evidence_span() -> None:
    with pytest.raises(ValidationError):
        _gap(supporting_evidence=[])


def test_confidence_is_a_band_never_a_percentage() -> None:
    gap = _gap(confidence=Confidence.MEDIUM, confidence_basis={"n_supporting": 2, "self_support": True})
    dumped = gap.model_dump(mode="json")
    assert dumped["confidence"] in {"high", "medium", "low"}
    assert not any(ch.isdigit() and "%" in str(dumped["confidence"]) for ch in str(dumped["confidence"]))
    assert isinstance(dumped["confidence_basis"], dict)


def test_defaults_mark_a_fresh_gap_as_a_candidate() -> None:
    gap = _gap()
    assert gap.user_state == GapUserState.CANDIDATE.value
    assert gap.self_support_passed is False
    assert gap.novelty_assessment == "under-addressed in this workspace"
