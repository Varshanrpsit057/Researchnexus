"""Deterministic `extraction_confidence` rule (Data Model §2 validation
rules) -- never asserted by the LLM (review §11, §18)."""

from __future__ import annotations

from app.domain.paper import Section
from app.domain.profile import Confidence, ProfileField, ProvenanceStatus

_HIGH_VERIFIED_RATIO = 0.8
_MEDIUM_VERIFIED_RATIO = 0.5
_LIMITATIONS_OR_FUTURE_WORK = {"limitations", "future work"}


def has_limitations_or_future_work_section(sections: list[Section]) -> bool:
    return any(s.title.strip().lower() in _LIMITATIONS_OR_FUTURE_WORK for s in sections)


def compute_extraction_confidence(fields: list[ProfileField], sections: list[Section]) -> Confidence:
    if not fields:
        return Confidence.LOW
    verified_ratio = sum(1 for f in fields if f.status == ProvenanceStatus.VERIFIED) / len(fields)
    if verified_ratio >= _HIGH_VERIFIED_RATIO and has_limitations_or_future_work_section(sections):
        return Confidence.HIGH
    if verified_ratio >= _MEDIUM_VERIFIED_RATIO:
        return Confidence.MEDIUM
    return Confidence.LOW
