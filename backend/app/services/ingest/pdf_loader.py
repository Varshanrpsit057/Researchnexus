"""Stage S2 (part 1): raw text/table/metadata extraction.

Deterministic code — no LLM calls (see docs/architecture/
ResearchNexus_Implementation_Architecture.md §2, row "Extract text + section
map + table blocks"). Uses pypdf for document metadata and pdfplumber for
per-page layout-aware text and tables.

Two-column handling: pdfplumber's own `page.extract_text()` assembles lines
purely by vertical position across the *full* page width, which interleaves
the two columns of a typical academic paper. `reading_order_text` instead
clusters words into columns by x-position first, then reads each column
top-to-bottom, left column before right column -- the reading order a human
would use (Architecture §3 S2; PDFTriage's structure-aware retrieval makes
the same point about respecting document layout).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pdfplumber
from pypdf import PdfReader

from app.config import Settings

_LINE_TOLERANCE_PT = 3.0
_MIN_WORDS_FOR_COLUMN_DETECTION = 20
_MIN_WORDS_PER_COLUMN = 10
_MIN_GUTTER_FRACTION_OF_WIDTH = 0.03


@dataclass(frozen=True)
class LoadedPage:
    number: int  # 1-indexed
    text: str
    tables: list[list[list[str | None]]] = field(default_factory=list)


@dataclass(frozen=True)
class RawPdfData:
    page_count: int
    pages: list[LoadedPage]
    title: str | None
    authors: list[str]
    warnings: list[str] = field(default_factory=list)


def _group_words_into_lines(words: list[dict]) -> list[list[dict]]:
    """Cluster words into visual lines by vertical position, then order each
    line left-to-right. `words` need not be pre-sorted."""
    ordered = sorted(words, key=lambda w: (round(w["top"] / _LINE_TOLERANCE_PT), w["x0"]))
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_top: float | None = None
    for w in ordered:
        if current_top is None or abs(w["top"] - current_top) <= _LINE_TOLERANCE_PT:
            current.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            lines.append(sorted(current, key=lambda x: x["x0"]))
            current = [w]
            current_top = w["top"]
    if current:
        lines.append(sorted(current, key=lambda x: x["x0"]))
    return lines


def _detect_column_split(words: list[dict], page_width: float) -> float | None:
    """Return the x-coordinate of a column gutter, or None for single-column.

    Looks for the largest horizontal gap between adjacent word x-centers
    that (a) sits roughly in the middle third of the page and (b) is wide
    enough to plausibly be a column gutter rather than normal word spacing.
    Requires a healthy number of words on both sides to avoid mis-splitting
    a sparse single-column page (e.g. a title page).
    """
    if len(words) < _MIN_WORDS_FOR_COLUMN_DETECTION:
        return None

    centers = sorted((w["x0"] + w["x1"]) / 2 for w in words)
    best_gap = 0.0
    best_mid: float | None = None
    for a, b in zip(centers, centers[1:], strict=False):
        mid = (a + b) / 2
        if page_width * 0.3 <= mid <= page_width * 0.7:
            gap = b - a
            if gap > best_gap:
                best_gap = gap
                best_mid = mid

    if best_mid is None or best_gap < page_width * _MIN_GUTTER_FRACTION_OF_WIDTH:
        return None

    left = sum(1 for c in centers if c < best_mid)
    right = len(centers) - left
    if left < _MIN_WORDS_PER_COLUMN or right < _MIN_WORDS_PER_COLUMN:
        return None
    return best_mid


def reading_order_text(page: pdfplumber.page.Page, max_chars: int) -> tuple[str, bool]:
    """Extract this page's text in human reading order.

    Returns (text, truncated). `truncated=True` means the page produced more
    than `max_chars` characters and was cut short -- the decompression-ratio
    guard from Architecture §3 S2 ("a single page yielding more raw
    characters than this is treated as suspicious").
    """
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:  # noqa: BLE001 - a single malformed page must not abort the document
        return "", False
    if not words:
        return "", False

    split_x = _detect_column_split(words, float(page.width))
    columns = (
        [words]
        if split_x is None
        else [
            [w for w in words if (w["x0"] + w["x1"]) / 2 < split_x],
            [w for w in words if (w["x0"] + w["x1"]) / 2 >= split_x],
        ]
    )

    parts: list[str] = []
    for column_words in columns:
        for line in _group_words_into_lines(column_words):
            joined = " ".join(w["text"] for w in line)
            # Some publisher typesetting pipelines embed a whole text block
            # twice, offset by roughly half a line height (observed live: a
            # ScienceDirect PDF whose abstract repeated every line verbatim
            # -- pdfplumber's own word extraction has no opinion on this and
            # faithfully returns both copies as separate lines, since the
            # vertical offset is well outside normal word-spacing jitter).
            # A real line of running prose repeating itself verbatim,
            # immediately after itself, does not otherwise happen.
            if parts and parts[-1] == joined:
                continue
            parts.append(joined)
    text = "\n".join(parts)

    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def _extract_authors(raw_author: str) -> list[str]:
    parts = re.split(r",|\band\b|;", raw_author)
    return [p.strip() for p in parts if p.strip()]


def load_pdf(pdf_bytes: bytes, settings: Settings) -> RawPdfData:
    """Load a PDF already known to be valid (see app.security.pdf_sanitizer).

    Never raises for per-page extraction problems -- a bad page is recorded
    as a warning with empty text/tables so one malformed page cannot fail
    the whole document (Architecture §3 S2 failure handling)."""
    warnings: list[str] = []

    title: str | None = None
    authors: list[str] = []
    try:
        info = PdfReader(io.BytesIO(pdf_bytes)).metadata
        if info is not None:
            if info.title and str(info.title).strip():
                title = str(info.title).strip()
            if info.author and str(info.author).strip():
                authors = _extract_authors(str(info.author))
    except Exception as e:  # noqa: BLE001 - metadata is best-effort
        warnings.append(f"metadata extraction failed: {e}")

    pages: list[LoadedPage] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text, truncated = reading_order_text(page, settings.max_page_chars)
            if truncated:
                warnings.append(
                    f"page {i}: text truncated at {settings.max_page_chars} chars "
                    "(possible decompression anomaly)"
                )
            try:
                raw_tables = page.extract_tables()
            except Exception as e:  # noqa: BLE001
                raw_tables = []
                warnings.append(f"page {i}: table extraction failed: {e}")
            pages.append(LoadedPage(number=i, text=text, tables=raw_tables))

    return RawPdfData(page_count=len(pages), pages=pages, title=title, authors=authors, warnings=warnings)
