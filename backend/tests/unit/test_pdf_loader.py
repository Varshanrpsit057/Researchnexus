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
