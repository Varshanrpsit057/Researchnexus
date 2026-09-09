from __future__ import annotations

from app.domain.paper import Section
from app.domain.profile import Confidence, ProfileField, ProvenanceStatus
from app.services.profile.confidence import (
    compute_extraction_confidence,
    has_limitations_or_future_work_section,
)


def _field(status: ProvenanceStatus) -> ProfileField:
    return ProfileField(value="x", status=status)


def _limitations_section() -> Section:
    return Section(title="Limitations", order=5, char_start=0, char_end=10, page_start=1, page_end=1)


def _no_limitations_sections() -> list[Section]:
    return [Section(title="1 Introduction", order=0, char_start=0, char_end=10, page_start=1, page_end=1)]


def test_high_requires_80pct_verified_and_limitations_section() -> None:
    fields = [_field(ProvenanceStatus.VERIFIED)] * 8 + [_field(ProvenanceStatus.UNVERIFIED)] * 2
    confidence = compute_extraction_confidence(fields, [_limitations_section()])
    assert confidence == Confidence.HIGH


def test_80pct_verified_without_limitations_section_is_only_medium() -> None:
    fields = [_field(ProvenanceStatus.VERIFIED)] * 8 + [_field(ProvenanceStatus.UNVERIFIED)] * 2
    confidence = compute_extraction_confidence(fields, _no_limitations_sections())
    assert confidence == Confidence.MEDIUM


def test_50pct_verified_is_medium() -> None:
    fields = [_field(ProvenanceStatus.VERIFIED)] * 5 + [_field(ProvenanceStatus.UNVERIFIED)] * 5
    confidence = compute_extraction_confidence(fields, [_limitations_section()])
    assert confidence == Confidence.MEDIUM


def test_below_50pct_verified_is_low() -> None:
    fields = [_field(ProvenanceStatus.VERIFIED)] * 3 + [_field(ProvenanceStatus.UNVERIFIED)] * 7
    confidence = compute_extraction_confidence(fields, [_limitations_section()])
    assert confidence == Confidence.LOW


def test_no_fields_is_low() -> None:
    assert compute_extraction_confidence([], [_limitations_section()]) == Confidence.LOW


def test_future_work_section_also_counts() -> None:
    section = Section(title="Future Work", order=5, char_start=0, char_end=10, page_start=1, page_end=1)
    assert has_limitations_or_future_work_section([section]) is True


def test_no_matching_section_returns_false() -> None:
    assert has_limitations_or_future_work_section(_no_limitations_sections()) is False
