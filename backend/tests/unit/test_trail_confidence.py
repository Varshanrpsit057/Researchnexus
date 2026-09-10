from __future__ import annotations

from app.domain.profile import Confidence
from app.domain.trail import RelationshipType
from app.services.trail.confidence import assign_confidence
from app.services.trail.rules import RuleResult


def _rule(rc: Confidence = Confidence.MEDIUM, agreement: int = 1, contradiction: bool = False) -> RuleResult:
    return RuleResult(
        relationship_type=RelationshipType.SIMILAR if not contradiction else RelationshipType.POTENTIALLY_CONTRADICTORY,
        rule_fired="x",
        evidence=[],
        rule_confidence=rc,
        signal_agreement=agreement,
        is_contradiction_candidate=contradiction,
    )


def test_llm_confirmed_high_rule_with_signal_agreement_is_high() -> None:
    conf, basis = assign_confidence(
        _rule(Confidence.HIGH, agreement=3), llm_confirmed=True, llm_certainty="high", evidence_count=2, session_present=True
    )
    assert conf == Confidence.HIGH
    assert basis["signal_agreement"] == 3
    assert basis["evidence_complete"] is True
    assert basis["llm_certainty"] == "high"


def test_no_session_caps_an_unconfirmed_rule_at_medium() -> None:
    conf, _ = assign_confidence(
        _rule(Confidence.HIGH, agreement=3), llm_confirmed=False, llm_certainty="none", evidence_count=2, session_present=False
    )
    assert conf == Confidence.MEDIUM


def test_llm_rejection_drops_the_edge_to_low_and_pending() -> None:
    conf, basis = assign_confidence(
        _rule(Confidence.HIGH, agreement=3), llm_confirmed=False, llm_certainty="low", evidence_count=1, session_present=True
    )
    assert conf == Confidence.LOW
    assert basis["llm_disagreed"] is True


def test_weak_rule_stays_low_even_when_confirmed() -> None:
    conf, _ = assign_confidence(
        _rule(Confidence.LOW, agreement=0), llm_confirmed=True, llm_certainty="low", evidence_count=1, session_present=True
    )
    assert conf == Confidence.LOW


def test_contradiction_needs_both_spans_and_high_certainty_for_high() -> None:
    high, _ = assign_confidence(
        _rule(Confidence.LOW, contradiction=True), llm_confirmed=True, llm_certainty="high", evidence_count=2, session_present=True
    )
    assert high == Confidence.MEDIUM  # contradiction edges are capped at MEDIUM in the MVP

    low, _ = assign_confidence(
        _rule(Confidence.LOW, contradiction=True), llm_confirmed=True, llm_certainty="medium", evidence_count=2, session_present=True
    )
    assert low == Confidence.LOW


def test_assignment_is_deterministic() -> None:
    args = dict(llm_confirmed=True, llm_certainty="medium", evidence_count=2, session_present=True)
    a = assign_confidence(_rule(Confidence.MEDIUM, agreement=2), **args)  # type: ignore[arg-type]
    b = assign_confidence(_rule(Confidence.MEDIUM, agreement=2), **args)  # type: ignore[arg-type]
    assert a == b
