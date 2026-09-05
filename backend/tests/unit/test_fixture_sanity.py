"""Sanity checks on the synthetic PDF fixtures themselves (test infra, not app code)."""

from __future__ import annotations

import io

import pdfplumber
import pypdf


def test_normal_paper_has_multiple_pages_and_text(normal_paper_pdf_bytes: bytes) -> None:
    reader = pypdf.PdfReader(io.BytesIO(normal_paper_pdf_bytes))
    assert len(reader.pages) >= 1
    assert not reader.is_encrypted
    text = reader.pages[0].extract_text() or ""
    assert "Introduction" in text or "Abstract" in text


def test_scanned_pdf_has_no_extractable_text(scanned_pdf_bytes: bytes) -> None:
    reader = pypdf.PdfReader(io.BytesIO(scanned_pdf_bytes))
    text = "".join((p.extract_text() or "") for p in reader.pages)
    assert text.strip() == ""


def test_encrypted_pdf_reports_encrypted(encrypted_pdf_bytes: bytes) -> None:
    reader = pypdf.PdfReader(io.BytesIO(encrypted_pdf_bytes))
    assert reader.is_encrypted


def test_corrupt_pdf_fails_to_open_cleanly() -> None:
    from tests.fixtures.make_fixtures import make_corrupt_pdf

    data = make_corrupt_pdf()
    opened_ok = False
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        # even if pypdf tolerates it, page access or count should misbehave
        _ = len(reader.pages)
        opened_ok = True
    except Exception:
        opened_ok = False
    assert opened_ok is False, "expected the truncated fixture to fail to open"


def test_two_column_pdf_has_words_on_both_sides(two_column_paper_pdf_bytes: bytes) -> None:
    with pdfplumber.open(io.BytesIO(two_column_paper_pdf_bytes)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        xs = [w["x0"] for w in words]
        mid = page.width / 2
        left = [x for x in xs if x < mid]
        right = [x for x in xs if x >= mid]
        assert len(left) > 5
        assert len(right) > 5
