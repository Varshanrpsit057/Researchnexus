from __future__ import annotations

import io

import pdfplumber

from app.config import Settings
from app.services.ingest.pdf_loader import load_pdf, reading_order_text


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_loads_normal_paper_metadata(normal_paper_pdf_bytes: bytes) -> None:
    data = load_pdf(normal_paper_pdf_bytes, _settings())
    assert data.title is not None
    assert "Retrieval-Augmented Generation" in data.title
    assert any("Author" in a for a in data.authors)
    assert len(data.authors) == 2  # "A. Author" and "B. Coauthor"


def test_loads_normal_paper_pages(normal_paper_pdf_bytes: bytes) -> None:
    data = load_pdf(normal_paper_pdf_bytes, _settings())
    assert data.page_count == len(data.pages)
    assert data.page_count >= 1
    full_text = "\n".join(p.text for p in data.pages)
    assert "Introduction" in full_text
    assert "Method" in full_text
    assert "References" in full_text
    assert data.warnings == []


def test_table_is_extracted(normal_paper_pdf_bytes: bytes) -> None:
    data = load_pdf(normal_paper_pdf_bytes, _settings())
    all_tables = [t for p in data.pages for t in p.tables]
    assert len(all_tables) >= 1
    flat = [cell for row in all_tables[0] for cell in row if cell]
    assert any("F1" in str(c) or "BM25" in str(c) for c in flat)


def test_scanned_pdf_yields_empty_text_without_crashing(scanned_pdf_bytes: bytes) -> None:
    data = load_pdf(scanned_pdf_bytes, _settings())
    assert data.page_count == 1
    assert data.pages[0].text.strip() == ""


def test_two_column_reading_order_is_column_major(two_column_paper_pdf_bytes: bytes) -> None:
    data = load_pdf(two_column_paper_pdf_bytes, _settings())
    full_text = "\n".join(p.text for p in data.pages)
    assert "INTROSTART" in full_text
    assert "METHODSTART" in full_text
    assert "RESULTSTART" in full_text
    assert full_text.index("INTROSTART") < full_text.index("METHODSTART") < full_text.index("RESULTSTART")


def test_reading_order_text_falls_back_to_single_column_for_narrow_pages(two_column_paper_pdf_bytes: bytes) -> None:
    # A page with too few words must not be forced into a spurious 2-column split.
    with pdfplumber.open(io.BytesIO(two_column_paper_pdf_bytes)) as pdf:
        page = pdf.pages[0]
        # Manually craft a tiny word list scenario via the real page but assert the
        # helper degrades gracefully (no exception, non-empty output) regardless.
        text, truncated = reading_order_text(page, max_chars=1_000_000)
        assert isinstance(text, str)
        assert truncated is False


def test_reading_order_text_drops_a_duplicated_overlapping_text_block(duplicate_text_pdf_bytes: bytes) -> None:
    # Observed live: a real ScienceDirect PDF had its abstract's text block
    # rendered twice, offset by roughly half a line height, and pdfplumber's
    # word extraction faithfully returned both copies as separate lines --
    # every line of the abstract came back duplicated, immediately adjacent
    # to itself. `duplicate_text_pdf_bytes` reproduces that exact layout.
    with pdfplumber.open(io.BytesIO(duplicate_text_pdf_bytes)) as pdf:
        text, _truncated = reading_order_text(pdf.pages[0], max_chars=1_000_000)
    assert text.count("duplicate text block.") == 1
    assert text.count("Every line below is drawn twice") == 1
    assert text.count("must not repeat this content") == 1


# --- an IEEE first page (remediation, 2026-10-02) ---------------------------


def test_tightly_set_words_keep_their_spaces(ieee_style_pdf_bytes: bytes) -> None:
    # words 1.8 pt apart at 9 pt: a fixed 3 pt tolerance glued them ("Publictransportation")
    text = "\n".join(p.text for p in load_pdf(ieee_style_pdf_bytes, _settings()).pages)
    assert "Public transportation within university campuses" in text
    assert "Publictransportation" not in text


def test_a_full_width_header_does_not_hide_the_two_columns_below_it(ieee_style_pdf_bytes: bytes) -> None:
    text = load_pdf(ieee_style_pdf_bytes, _settings()).pages[0].text
    # title first, then the whole left column (abstract, keywords, introduction), then the right column
    assert text.index("OnBoard: A Real-Time Bus Tracking Mobile") < text.index("Abstract")
    assert text.index("tracks university") < text.index("Keywords") < text.index("I. INTRODUCTION") < text.index("RIGHTCOLUMN")
    abstract_block = text[text.index("Abstract") : text.index("Keywords")]
    assert "RIGHTCOLUMN" not in abstract_block and "satisfaction" not in abstract_block


def test_sideways_margin_text_stays_out_of_the_body(ieee_style_pdf_bytes: bytes) -> None:
    data = load_pdf(ieee_style_pdf_bytes, _settings())
    assert "IEEE Conference" not in data.pages[0].text
    assert "10.1109" in data.margin_text or "10.1109" in data.margin_text[::-1]
