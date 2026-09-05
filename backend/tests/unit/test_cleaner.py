from __future__ import annotations

from app.config import Settings
from app.services.ingest.cleaner import (
    build_full_text,
    clean_page_text,
    clean_pages,
    strip_repeated_headers_footers,
)
from app.services.ingest.pdf_loader import load_pdf


def test_dehyphenation_joins_split_word() -> None:
    text = "We use a dense retriev-\nal system with a cross-encoder rerank-\ner."
    cleaned = clean_page_text(text)
    assert "retrieval" in cleaned
    assert "reranker" in cleaned
    assert "retriev-" not in cleaned


def test_whitespace_normalized_without_destroying_content() -> None:
    text = "alpha   beta\t\tgamma\n\n\n\ndelta\nepsilon"
    cleaned = clean_page_text(text)
    assert "alpha beta gamma" in cleaned
    assert "\n\n\n" not in cleaned  # 4 blank lines collapsed
    assert "\n\n" in cleaned  # a paragraph break is preserved
    assert "delta" in cleaned and "epsilon" in cleaned


def test_non_ascii_scientific_symbols_preserved() -> None:
    text = "The loss uses α and β with p < 0.05 (F1 = 58.6%)."
    cleaned = clean_page_text(text)
    assert "α" in cleaned and "β" in cleaned
    assert "p < 0.05" in cleaned
    assert "58.6%" in cleaned
    assert cleaned == cleaned  # never lowercased / mutated case
    assert "F1" in cleaned


def test_strip_repeated_headers_and_footers() -> None:
    pages = [
        "RUNNING HEADER\nUnique body text for page one.\nPage 1",
        "RUNNING HEADER\nUnique body text for page two.\nPage 2",
        "RUNNING HEADER\nUnique body text for page three.\nPage 3",
    ]
    cleaned = strip_repeated_headers_footers(pages)
    for original, result in zip(pages, cleaned, strict=True):
        assert "RUNNING HEADER" not in result
        assert "Page " not in result
        assert "Unique body text" in result
        # the unique sentence itself must be untouched
        unique_line = [line for line in original.splitlines() if "Unique body" in line][0]
        assert unique_line in result


def test_does_not_strip_a_line_that_only_appears_once() -> None:
    pages = [
        "shared header\nbody one\nSPECIAL ONE-OFF LINE",
        "shared header\nbody two",
        "shared header\nbody three",
        "shared header\nbody four",
        "shared header\nbody five",
    ]
    cleaned = strip_repeated_headers_footers(pages)
    assert "SPECIAL ONE-OFF LINE" in cleaned[0]
    assert "shared header" not in cleaned[0]


def test_build_full_text_offsets_are_correct() -> None:
    pages = ["hello world", "second page text", "third"]
    full_text, ranges = build_full_text(pages)
    assert len(ranges) == 3
    for text, (start, end) in zip(pages, ranges, strict=True):
        assert full_text[start:end] == text


def test_clean_pages_pipeline_end_to_end() -> None:
    cleaned, full_text, ranges = clean_pages(
        [
            "HEADER\nAlpha section text.\nPage 1",
            "HEADER\nBeta section text.\nPage 2",
            "HEADER\nGamma section text.\nPage 3",
        ]
    )
    assert len(ranges) == 3
    assert "HEADER" not in full_text
    assert "Alpha section" in full_text
    assert "Beta section" in full_text


def test_real_fixture_header_footer_is_stripped(normal_paper_pdf_bytes: bytes) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    raw = load_pdf(normal_paper_pdf_bytes, settings)
    page_texts = [p.text for p in raw.pages]
    _cleaned, full_text, _ranges = clean_pages(page_texts)
    assert "ResearchNexus Synthetic Test Paper" not in full_text
    assert "Introduction" in full_text
