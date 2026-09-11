from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.direction import DirectionKind, DirectionUserState, ResearchDirection
from app.domain.gap import GapEvidence
from app.domain.profile import Confidence, SourceSpan


def _direction(**kw: object) -> ResearchDirection:
    base: dict = {
        "direction_id": "dir_1",
        "workspace_id": "ws_1",
        "gap_id": "gap_1",
        "proposal": "Apply contrastive pretraining to dense retrieval.",
        "motivation": "The gap shows no paper applies it.",
        "supporting_evidence": [GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="we study dense retrieval"))],
        "kind": DirectionKind.LLM_HYPOTHESIS.value,
    }
    base.update(kw)
    return ResearchDirection(**base)


def test_kind_is_mandatory_and_validated() -> None:
    with pytest.raises(ValidationError):
        _direction(kind="something_else")
    d = _direction(kind="evidence_backed_inference")
    assert d.kind == "evidence_backed_inference"


def test_direction_must_inherit_gap_evidence() -> None:
    with pytest.raises(ValidationError):
        _direction(supporting_evidence=[])


def test_critique_scores_are_clamped_and_feasibility_is_capped() -> None:
    d = _direction(critique={"novelty": 9, "specificity": 0, "feasibility": 5, "groundedness": 4})
    assert d.critique == {"novelty": 5, "specificity": 1, "feasibility": 3, "groundedness": 4}


def test_confidence_is_a_band_never_a_percentage() -> None:
    d = _direction(confidence=Confidence.MEDIUM, confidence_basis={"groundedness": 4, "low_critique": False})
    dumped = d.model_dump(mode="json")
    assert dumped["confidence"] in {"high", "medium", "low"}
    assert isinstance(dumped["confidence_basis"], dict)


def test_defaults_mark_a_fresh_direction_as_candidate() -> None:
    d = _direction()
    assert d.user_state == DirectionUserState.CANDIDATE.value
    assert d.flags == []
    assert d.gap_id == "gap_1"
