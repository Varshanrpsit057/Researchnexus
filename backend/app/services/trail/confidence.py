"""Deterministic confidence band for a trail edge (Architecture §3 S11
`confidence.py`). Fixed rules, NOT a calibrated model -- calibration (ECE,
reliability curves) is Phase 16 (Evaluation Plan §4). The band is a
function of: the rule's own strength, how many ranking signals agree,
whether the evidence is complete, and the LLM's certainty when it ran.

High-precision MVP policy:
- `HIGH` is only reachable with an LLM confirmation on top of a strong rule
  (rule_confidence HIGH + >=2 agreeing signals + complete evidence);
- an LLM that ran and DISAGREED  -> `LOW` (caller keeps `user_state=pending`);
- an unconfirmed rule (no LLM available) -> at most `MEDIUM`;
- contradiction edges -> capped at `MEDIUM` even when fully confirmed
  (false contradictions are costly).
"""

from __future__ import annotations

from app.domain.profile import Confidence
from app.domain.trail import RelationshipType
from app.services.trail.rules import RuleResult

_HIGH_SIGNAL_AGREEMENT = 2
# citation-fact rules: the seed<->target citation IS the strong signal, so
# they don't also need >=2 agreeing *ranking* signals to reach HIGH.
_CITATION_FACT_TYPES = {RelationshipType.FOUNDATIONAL, RelationshipType.METHOD_EXTENSION}


def assign_confidence(
    rule_result: RuleResult,
    *,
    llm_confirmed: bool,
    llm_certainty: str,
    evidence_count: int,
    session_present: bool,
) -> tuple[Confidence, dict]:
    is_contradiction = rule_result.is_contradiction_candidate
    evidence_complete = evidence_count >= (2 if is_contradiction else 1)

    basis: dict = {
        "signal_agreement": rule_result.signal_agreement,
        "evidence_complete": evidence_complete,
        "rule_confidence": rule_result.rule_confidence.value,
        "llm_certainty": llm_certainty,
        "llm_disagreed": session_present and not llm_confirmed and not is_contradiction,
    }

    if is_contradiction:
        band = Confidence.MEDIUM if (llm_confirmed and llm_certainty == "high" and evidence_complete) else Confidence.LOW
        return band, basis

    if session_present and not llm_confirmed:
        return Confidence.LOW, basis

    strong_support = (
        rule_result.signal_agreement >= _HIGH_SIGNAL_AGREEMENT
        or rule_result.relationship_type in _CITATION_FACT_TYPES
    )
    if (
        llm_confirmed
        and llm_certainty in ("high", "medium")
        and rule_result.rule_confidence is Confidence.HIGH
        and evidence_complete
        and strong_support
    ):
        return Confidence.HIGH, basis

    if rule_result.rule_confidence is Confidence.LOW and rule_result.signal_agreement == 0:
        return Confidence.LOW, basis

    return Confidence.MEDIUM, basis
