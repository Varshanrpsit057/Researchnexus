from __future__ import annotations

from app.config import Settings
from app.domain.paper import ParseConfidence, RawReference, Section
from app.services.ingest.cleaner import clean_pages
from app.services.ingest.confidence import assess_confidence
from app.services.ingest.pdf_loader import load_pdf
from app.services.ingest.reference_parser import parse_references
from app.services.ingest.section_splitter import split_sections

_LONG_TEXT = "This is a sentence about retrieval augmented generation. " * 30


def _real_sections() -> list[Section]:
    return [
        Section(title="1 Introduction", order=0, char_start=0, char_end=100, page_start=1, page_end=1),
        Section(title="2 Method", order=1, char_start=100, char_end=200, page_start=1, page_end=2),
    ]


def _fallback_sections(full_text: str) -> list[Section]:
    return [
        Section(
            title="Body",
            order=0,
            char_start=0,
            char_end=len(full_text),
            page_start=1,
            page_end=1,
            is_fallback=True,
        )
    ]


def test_high_confidence_for_well_structured_paper() -> None:
    confidence, warnings = assess_confidence(
        page_count=2,
        full_text=_LONG_TEXT,
        sections=_real_sections(),
        references=[RawReference(order=0, raw_text="A ref.")],
        has_text_layer=True,
    )
    assert confidence == ParseConfidence.HIGH
    assert warnings == []


def test_low_confidence_when_no_text_layer() -> None:
    confidence, warnings = assess_confidence(
        page_count=1,
        full_text="",
        sections=[],
        references=[],
        has_text_layer=False,
    )
    assert confidence == ParseConfidence.LOW
    assert warnings


def test_low_confidence_for_fallback_section() -> None:
    confidence, warnings = assess_confidence(
        page_count=1,
        full_text=_LONG_TEXT,
        sections=_fallback_sections(_LONG_TEXT),
        references=[],
        has_text_layer=True,
    )
    assert confidence == ParseConfidence.LOW
    assert any("fallback" in w for w in warnings)


def test_medium_confidence_when_no_references_found() -> None:
    confidence, _warnings = assess_confidence(
        page_count=2,
        full_text=_LONG_TEXT,
        sections=_real_sections(),
        references=[],
        has_text_layer=True,
    )
    assert confidence == ParseConfidence.MEDIUM


def test_low_confidence_for_sparse_text() -> None:
    confidence, _warnings = assess_confidence(
        page_count=5,
        full_text="short",
        sections=_real_sections(),
        references=[RawReference(order=0, raw_text="A ref.")],
        has_text_layer=True,
    )
    assert confidence == ParseConfidence.LOW


def test_real_fixture_is_high_or_medium_confidence(normal_paper_pdf_bytes: bytes) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    raw = load_pdf(normal_paper_pdf_bytes, settings)
    _cleaned, full_text, ranges = clean_pages([p.text for p in raw.pages])
    sections = split_sections(full_text, ranges)
    refs = parse_references(full_text, sections)
    confidence, _warnings = assess_confidence(
        page_count=raw.page_count,
        full_text=full_text,
        sections=sections,
        references=refs,
        has_text_layer=True,
    )
    assert confidence in (ParseConfidence.HIGH, ParseConfidence.MEDIUM)
