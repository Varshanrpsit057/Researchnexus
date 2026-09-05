"""Stage S2 (part 2): clean per-page text without destroying scientific content.

Deterministic code. Three responsibilities, kept separate and composable:
1. `strip_repeated_headers_footers` -- remove running headers/footers/page
   numbers that recur across most pages (Architecture §3 S2: "strip repeated
   headers/footers").
2. `clean_page_text` -- de-hyphenate line-break-split words and normalise
   whitespace, WITHOUT lowercasing, stripping non-ASCII (math symbols,
   Greek letters), or touching punctuation that carries scientific meaning
   (e.g. "p < 0.05", "58.6%").
3. `build_full_text` -- join cleaned per-page text into one string while
   recording each page's exact character range, so downstream stages
   (section splitting, chunking) can report accurate provenance.
"""

from __future__ import annotations

import re
from collections import Counter

_HYPHEN_LINEBREAK_RE = re.compile(r"(\w)-\n(\w)")
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_BLANK_LINE_RE = re.compile(r"\n{3,}")
_DIGIT_RE = re.compile(r"\d+")

_PAGE_SEPARATOR = "\n\n"


def clean_page_text(text: str) -> str:
    """De-hyphenate and normalise whitespace for a single page's text."""
    text = _HYPHEN_LINEBREAK_RE.sub(r"\1\2", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_BLANK_LINE_RE.sub("\n\n", text)
    return text.strip()


def _normalize_for_repetition(line: str) -> str:
    """Signature used to detect a repeated header/footer even when it
    contains a changing page number (e.g. 'Page 1', 'Page 2', ...)."""
    return _DIGIT_RE.sub("#", line.strip().lower())


def strip_repeated_headers_footers(page_texts: list[str], min_fraction: float = 0.6) -> list[str]:
    """Remove lines whose (digit-normalised) signature recurs on at least
    `min_fraction` of pages. Requires >= 3 pages to be meaningful; with
    fewer pages, nothing is stripped (too little evidence of repetition)."""
    if len(page_texts) < 3:
        return list(page_texts)

    signature_counts: Counter[str] = Counter()
    for text in page_texts:
        signatures = {_normalize_for_repetition(line) for line in text.splitlines() if line.strip()}
        signature_counts.update(signatures)

    threshold = max(2, round(len(page_texts) * min_fraction))
    repeated = {sig for sig, count in signature_counts.items() if count >= threshold and 0 < len(sig) < 120}

    cleaned_pages = []
    for text in page_texts:
        kept_lines = [line for line in text.splitlines() if _normalize_for_repetition(line) not in repeated]
        cleaned_pages.append("\n".join(kept_lines))
    return cleaned_pages


def build_full_text(page_texts: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """Join per-page text into one string; return (full_text, page_ranges)
    where page_ranges[i] = (char_start, char_end) of page i+1 in full_text."""
    parts: list[str] = []
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for i, text in enumerate(page_texts):
        start = cursor
        parts.append(text)
        cursor += len(text)
        ranges.append((start, cursor))
        if i < len(page_texts) - 1:
            parts.append(_PAGE_SEPARATOR)
            cursor += len(_PAGE_SEPARATOR)
    return "".join(parts), ranges


def clean_pages(page_texts: list[str]) -> tuple[list[str], str, list[tuple[int, int]]]:
    """Full per-page cleaning pipeline.

    Returns (cleaned_page_texts, full_text, page_char_ranges).
    """
    stripped = strip_repeated_headers_footers(page_texts)
    cleaned = [clean_page_text(t) for t in stripped]
    full_text, ranges = build_full_text(cleaned)
    return cleaned, full_text, ranges
