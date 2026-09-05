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
