from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.profile import Confidence, SourceSpan
from app.domain.trail import (
    DetectionMethod,
    Evidence,
    RelationshipType,
    TrailEdge,
    UserState,
)


def test_relationship_type_has_all_seven_values() -> None:
    assert {t.value for t in RelationshipType} == {
        "SIMILAR",
        "FOUNDATIONAL",
        "RECENT",
        "COMPETING",
        "METHOD_EXTENSION",
        "DATASET_RELATED",
        "POTENTIALLY_CONTRADICTORY",
    }


def test_detection_method_values() -> None:
    assert {m.value for m in DetectionMethod} == {"rule", "rule_llm_confirmed", "contradiction_nli", "user"}


def _edge(**kw: object) -> TrailEdge:
    base: dict[str, object] = {
        "edge_id": "edge_1",
        "run_id": "run_1",
        "source_paper_id": "pap_seed",
        "target_paper_id": "pap_x",
        "relationship_type": RelationshipType.SIMILAR,
        "detection_method": DetectionMethod.RULE,
        "evidence": [Evidence(span=SourceSpan(paper_id="pap_x", quote="a relevant sentence"), role="target_claim")],
        "confidence": Confidence.MEDIUM,
    }
    base.update(kw)
    return TrailEdge(**base)  # type: ignore[arg-type]


def test_trail_edge_defaults() -> None:
    edge = _edge()
    assert edge.user_state == "pending"
    assert edge.llm_confirmed is False
    assert edge.rule_fired is None
    assert edge.supporting_references == []
    assert edge.workspace_id is None


def test_trail_edge_requires_at_least_one_piece_of_evidence() -> None:
    with pytest.raises(ValidationError):
        _edge(evidence=[])


def test_trail_edge_round_trips_through_json_ignoring_timestamp() -> None:
    edge = _edge(relationship_type=RelationshipType.FOUNDATIONAL, confidence=Confidence.HIGH)
    restored = TrailEdge.model_validate(edge.model_dump(mode="json"))
    assert restored.model_dump(exclude={"created_at"}) == edge.model_dump(exclude={"created_at"})


def test_user_state_enum() -> None:
    assert {s.value for s in UserState} == {"pending", "accepted", "rejected"}
