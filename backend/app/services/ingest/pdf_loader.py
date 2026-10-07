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
# A gap counts as a word break when it is wider than this share of the font
# size (pdfplumber's fixed 3 pt default glued the words of tightly set LaTeX
# papers together -- "CurrentadvancesinAImodels" -- measured on 129 stored
# PDFs: 301 glued words at 3 pt, 1 at this ratio, and no word split apart).
_WORD_GAP_RATIO = 0.15
# A line whose two halves are this close across the gutter runs across it
# (a centred title, an author block), wider than any word space.
_SPANNING_GAP_PT = 8.0


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
    # text set sideways (a publisher's margin stamp: DOI, licence), kept out
    # of the body and read only for identifiers
    margin_text: str = ""


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

    The gutter is the x in the middle of the page that the fewest lines run
    across: body lines of a two-column page never do, while a full-width
    title or author block above them does -- which is why the earlier
    "largest gap between word centres" test failed on the first page of a
    real IEEE paper (its centred title and author block filled the gutter,
    so the page was read straight across both columns). Requires most lines
    to keep clear of the gutter and enough words on each side, so a
    single-column page is never split.
    """
    if len(words) < _MIN_WORDS_FOR_COLUMN_DETECTION:
        return None
    lines = _group_words_into_lines(words)
    if len(lines) < 6:
        return None

    lo, hi = page_width * 0.3, page_width * 0.7
    best_x: float | None = None
    best_cover = len(lines) + 1
    x = lo
    while x <= hi:
        cover = sum(1 for line in lines if any(w["x0"] <= x <= w["x1"] for w in line))
        if cover < best_cover:
            best_cover, best_x = cover, x
        x += 1.0
    if best_x is None or best_cover > len(lines) * 0.25:
        return None

    # the gap around it must be a gutter, not one ragged line end
    left_edge = max((w["x1"] for w in words if w["x1"] <= best_x), default=None)
    right_edge = min((w["x0"] for w in words if w["x0"] >= best_x), default=None)
    if left_edge is None or right_edge is None:
        return None
    clear = [w for w in words if not (w["x0"] < best_x < w["x1"])]
    left = sum(1 for w in clear if (w["x0"] + w["x1"]) / 2 < best_x)
    right = len(clear) - left
    if left < _MIN_WORDS_PER_COLUMN or right < _MIN_WORDS_PER_COLUMN:
        return None
    two_sided = sum(
        1
        for line in lines
        if any(w["x1"] <= best_x for w in line) and any(w["x0"] >= best_x for w in line)
    )
    if two_sided < len(lines) * 0.2:  # most lines have text on both sides of a real gutter
        return None
    return best_x


def _join(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def _reading_order_lines(words: list[dict], page_width: float) -> list[str]:
    """The page's lines in reading order. On a two-column page, a line that
    runs across the gutter (a title, an author block, a full-width figure
    caption) is read where it stands; between such lines, the left column is
    read before the right one."""
    lines = _group_words_into_lines(words)
    split_x = _detect_column_split(words, page_width)
    if split_x is None:
        return [_join(line) for line in lines]

    out: list[str] = []
    left: list[list[dict]] = []
    right: list[list[dict]] = []

    def flush() -> None:
        out.extend(_join(line) for line in left)
        out.extend(_join(line) for line in right)
        left.clear()
        right.clear()

    for line in lines:
        lhs = [w for w in line if (w["x0"] + w["x1"]) / 2 < split_x]
        rhs = [w for w in line if (w["x0"] + w["x1"]) / 2 >= split_x]
        crosses = any(w["x0"] < split_x < w["x1"] for w in line)
        joined_across = bool(lhs and rhs) and min(w["x0"] for w in rhs) - max(w["x1"] for w in lhs) < _SPANNING_GAP_PT
        if crosses or joined_across:
            flush()
            out.append(_join(line))
            continue
        if lhs:
            left.append(lhs)
        if rhs:
            right.append(rhs)
    flush()
    return out


def _page_words(page: pdfplumber.page.Page) -> tuple[list[dict], str]:
    """The page's upright words, and its sideways text (a margin stamp)."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False, x_tolerance_ratio=_WORD_GAP_RATIO)
    upright = [w for w in words if w.get("upright", True)]
    sideways = " ".join(w["text"] for w in words if not w.get("upright", True))
    return upright, sideways


def _page_text(page: pdfplumber.page.Page, max_chars: int) -> tuple[str, bool, str]:
    try:
        words, sideways = _page_words(page)
    except Exception:  # noqa: BLE001 - a single malformed page must not abort the document
        return "", False, ""
    if not words:
        return "", False, sideways

    parts: list[str] = []
    for joined in _reading_order_lines(words, float(page.width)):
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
        return text[:max_chars], True, sideways
    return text, False, sideways


def reading_order_text(page: pdfplumber.page.Page, max_chars: int) -> tuple[str, bool]:
    """Extract this page's text in human reading order.

    Returns (text, truncated). `truncated=True` means the page produced more
    than `max_chars` characters and was cut short -- the decompression-ratio
    guard from Architecture §3 S2 ("a single page yielding more raw
    characters than this is treated as suspicious").
    """
    text, truncated, _sideways = _page_text(page, max_chars)
    return text, truncated


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
    margins: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text, truncated, sideways = _page_text(page, settings.max_page_chars)
            if sideways and i <= 2:
                margins.append(sideways)
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

    return RawPdfData(
        page_count=len(pages),
        pages=pages,
        title=title,
        authors=authors,
        warnings=warnings,
        margin_text=" ".join(margins),
    )
