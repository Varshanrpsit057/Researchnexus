from __future__ import annotations

from app.config import Settings
from app.services.ingest.cleaner import clean_pages
from app.services.ingest.pdf_loader import load_pdf
from app.services.ingest.section_splitter import split_sections


def test_no_headings_falls_back_to_single_body_section() -> None:
    full_text = "just some plain prose with no headings at all, spanning one page."
    sections = split_sections(full_text, page_ranges=[(0, len(full_text))])
    assert len(sections) == 1
    assert sections[0].title == "Body"
    assert sections[0].is_fallback is True
    assert sections[0].char_start == 0
    assert sections[0].char_end == len(full_text)


def test_detects_keyword_and_numbered_headings() -> None:
    full_text = (
        "Abstract\n"
        "This is the abstract text of the paper.\n"
        "1 Introduction\n"
        "This is the introduction body text.\n"
        "2 Related Work\n"
        "This is related work body text.\n"
        "References\n"
        "[1] Someone, A paper, 2020.\n"
    )
    sections = split_sections(full_text, page_ranges=[(0, len(full_text))])
    titles = [s.title for s in sections]
    assert titles == ["Abstract", "1 Introduction", "2 Related Work", "References"]
    assert [s.order for s in sections] == [0, 1, 2, 3]
    for s in sections:
        assert s.char_end > s.char_start
        assert full_text[s.char_start : s.char_start + len(s.title)] == s.title


def test_does_not_false_positive_on_numbered_body_sentences() -> None:
    full_text = (
        "1 Introduction\n"
        "3.14 is an approximation of pi that appears in many equations used here.\n"
        "2 Method\n"
        "We evaluate at 5 different noise levels for robustness.\n"
    )
    sections = split_sections(full_text, page_ranges=[(0, len(full_text))])
    titles = [s.title for s in sections]
    assert titles == ["1 Introduction", "2 Method"]


def test_detects_numbered_headings_with_a_period_after_the_number() -> None:
    # "1. Introduction" / "3. Data and Methods" -- observed live in a real
    # ScienceDirect paper whose every heading used this style; the original
    # regex only matched a period-free "1 Introduction", so it found zero
    # numbered headings in that document and section detection fell back to
    # treating the entire body as one section.
    full_text = (
        "Abstract\n"
        "This is the abstract text of the paper.\n"
        "1. Introduction\n"
        "This is the introduction body text.\n"
        "2. Related Work\n"
        "This is related work body text.\n"
        "References\n"
        "[1] Someone, A paper, 2020.\n"
    )
    sections = split_sections(full_text, page_ranges=[(0, len(full_text))])
    titles = [s.title for s in sections]
    assert titles == ["Abstract", "1. Introduction", "2. Related Work", "References"]


def test_detects_roman_numeral_ieee_style_headings() -> None:
    # "I. INTRODUCTION" / "V. RESULT" -- observed live in a real IEEE
    # conference paper whose every heading used this style; neither the
    # period-free nor the period-after-arabic-number pattern matched a
    # roman numeral, so this document also fell back to one giant section.
    full_text = (
        "Abstract\n"
        "This is the abstract text of the paper.\n"
        "I. INTRODUCTION\n"
        "This is the introduction body text.\n"
        "II. RELATED WORK\n"
        "This is related work body text.\n"
        "REFERENCES\n"
        "[1] Someone, A paper, 2020.\n"
    )
    sections = split_sections(full_text, page_ranges=[(0, len(full_text))])
    titles = [s.title for s in sections]
    assert titles == ["Abstract", "I. INTRODUCTION", "II. RELATED WORK", "REFERENCES"]


def test_page_span_is_computed_from_page_ranges() -> None:
    page1 = "1 Introduction\nSome intro text that stays on page one.\n"
    page2 = "2 Method\nSome method text that is on page two.\n"
    full_text = page1 + "\n\n" + page2
    ranges = [(0, len(page1)), (len(page1) + 2, len(page1) + 2 + len(page2))]
    sections = split_sections(full_text, page_ranges=ranges)
    assert sections[0].page_start == 1
    assert sections[1].page_start == 2


def test_real_fixture_produces_expected_section_titles(normal_paper_pdf_bytes: bytes) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    raw = load_pdf(normal_paper_pdf_bytes, settings)
    _cleaned, full_text, ranges = clean_pages([p.text for p in raw.pages])
    sections = split_sections(full_text, ranges)
    titles = [s.title for s in sections]
    for expected in ["Abstract", "1 Introduction", "2 Related Work", "3 Method", "References"]:
        assert expected in titles, f"missing {expected!r} in {titles}"
    assert titles == sorted(titles, key=titles.index)  # sections in document order


def test_a_table_column_header_repeated_through_the_paper_is_not_a_section() -> None:
    # 2026-10-07: a real arXiv paper's tables each had a "Method" column
    # header on its own line, which made eight "Method" sections
    text = (
        "1 Introduction\nWe study driving.\n"
        "2 Experiments\nTable 1.\nMethod\nOurs 0.9\n"
        "Table 2.\nMethod\nOurs 0.8\n"
        "Table 3.\nMethod\nOurs 0.7\n"
        "3 Conclusion\nIt works.\n"
    )
    titles = [s.title for s in split_sections(text, [(0, len(text))])]
    assert titles == ["1 Introduction", "2 Experiments", "3 Conclusion"]


def test_a_single_unnumbered_method_heading_is_still_a_section() -> None:
    text = "Abstract\nWe propose.\nIntroduction\nIt matters.\nMethod\nWe do this.\nResults\nIt is better.\n"
    titles = [s.title for s in split_sections(text, [(0, len(text))])]
    assert titles == ["Abstract", "Introduction", "Method", "Results"]


def test_a_repeated_abstract_keeps_the_papers_own_and_drops_the_later_ones() -> None:
    # a paper whose appendix shows prompts with "Abstract" fields keeps its own abstract
    text = (
        "Abstract\nWe search papers.\n1 Introduction\nIt matters.\n"
        "A Prompts\nAbstract\n{abstract}\nAbstract\n{abstract}\nAbstract\n{abstract}\n"
    )
    titles = [s.title for s in split_sections(text, [(0, len(text))])]
    assert titles == ["Abstract", "1 Introduction"]
