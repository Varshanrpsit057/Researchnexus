from __future__ import annotations

from app.config import Settings
from app.services.ingest.cleaner import clean_pages
from app.services.ingest.pdf_loader import load_pdf
from app.services.ingest.reference_parser import parse_references
from app.services.ingest.section_splitter import split_sections


def test_no_references_section_returns_empty_list() -> None:
    full_text = "1 Introduction\nsome text\n"
    sections = split_sections(full_text, [(0, len(full_text))])
    assert parse_references(full_text, sections) == []


def test_bracket_numbered_references_are_split() -> None:
    full_text = (
        "1 Introduction\n"
        "Some introduction text.\n"
        "References\n"
        "[1] A. Author. First paper. 2019.\n"
        "[2] B. Writer. Second paper. 2020.\n"
        "[3] C. Scholar. Third paper. 2021.\n"
    )
    sections = split_sections(full_text, [(0, len(full_text))])
    refs = parse_references(full_text, sections)
    assert [r.order for r in refs] == [0, 1, 2]
    assert "First paper" in refs[0].raw_text
    assert "Second paper" in refs[1].raw_text
    assert "Third paper" in refs[2].raw_text


def test_number_dot_references_are_split_when_no_brackets() -> None:
    full_text = (
        "1 Introduction\n"
        "Some introduction text.\n"
        "References\n"
        "1. A. Author. First paper. 2019.\n"
        "2. B. Writer. Second paper. 2020.\n"
    )
    sections = split_sections(full_text, [(0, len(full_text))])
    refs = parse_references(full_text, sections)
    assert len(refs) == 2
    assert "First paper" in refs[0].raw_text


def test_wrapped_bracket_reference_is_joined_into_one_entry() -> None:
    full_text = (
        "1 Introduction\n"
        "Some introduction text.\n"
        "References\n"
        "[1] A. Author. A paper with a\n"
        "very long title that wraps.\n"
        "2019.\n"
        "[2] B. Writer. Second paper. 2020.\n"
    )
    sections = split_sections(full_text, [(0, len(full_text))])
    refs = parse_references(full_text, sections)
    assert len(refs) == 2
    assert "very long title that wraps" in refs[0].raw_text
    assert "\n" not in refs[0].raw_text


def test_fallback_blank_line_blocks_when_no_markers() -> None:
    full_text = (
        "1 Introduction\n"
        "Some introduction text.\n"
        "References\n"
        "Author one. Paper one. 2019.\n"
        "\n"
        "Author two. Paper two. 2020.\n"
    )
    sections = split_sections(full_text, [(0, len(full_text))])
    refs = parse_references(full_text, sections)
    assert len(refs) == 2
    assert "Paper one" in refs[0].raw_text
    assert "Paper two" in refs[1].raw_text


def test_real_fixture_extracts_five_references(normal_paper_pdf_bytes: bytes) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    raw = load_pdf(normal_paper_pdf_bytes, settings)
    _cleaned, full_text, _ranges = clean_pages([p.text for p in raw.pages])
    sections = split_sections(full_text, _ranges)
    refs = parse_references(full_text, sections)
    assert len(refs) == 5
    assert all("topic" in r.raw_text for r in refs)
