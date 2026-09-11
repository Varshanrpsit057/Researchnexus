"""Deterministic confidence band for a direction (Roadmap Phase 12).

`confidence` derives **only** from `confidence_basis`: the direction's
`kind`, its critique scores, and the accepted gap's own `confidence` /
`self_support_passed`. A fixed rule, not a calibrated model -- calibration
is Phase 16, same policy as the Phase 7 trail and Phase 11 gap bands.
"""

from __future__ import annotations

from app.domain.gap import ResearchGap
from app.domain.profile import Confidence

_LOW_CRITIQUE_THRESHOLD = 2


def assign_confidence(kind: str, critique: dict, gap: ResearchGap) -> tuple[Confidence, dict]:
    groundedness = int(critique.get("groundedness", 1))
    specificity = int(critique.get("specificity", 1))
    novelty = int(critique.get("novelty", 1))
    feasibility = int(critique.get("feasibility", 1))
    low_critique = bool(critique) and min(critique.values()) <= _LOW_CRITIQUE_THRESHOLD

    basis: dict = {
        "kind": kind,
        "groundedness": groundedness,
        "specificity": specificity,
        "novelty": novelty,
        "feasibility": feasibility,
        "gap_confidence": gap.confidence.value,
        "gap_self_support": gap.self_support_passed,
        "low_critique": low_critique,
    }

    if not gap.self_support_passed:
        return Confidence.LOW, basis

    strong_kind = kind == "evidence_backed_inference"
    if (
        strong_kind
        and groundedness >= 4
        and specificity >= 3
        and gap.confidence in (Confidence.HIGH, Confidence.MEDIUM)
    ):
        return Confidence.HIGH, basis
    if groundedness >= 3 and specificity >= 2:
        return Confidence.MEDIUM, basis
    return Confidence.LOW, basis
