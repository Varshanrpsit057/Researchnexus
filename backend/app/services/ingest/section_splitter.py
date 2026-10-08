"""Stage S2 (part 3): detect section headings and build Section objects.

Deterministic, regex/heuristic-based (Architecture §3 S2). Two heading
shapes are recognised: a fixed vocabulary of common academic section names
("Abstract", "References", ...) and numbered headings ("1 Introduction",
"3.2 Ablations"). If fewer than two headings are found, the whole document
becomes a single fallback "Body" section (Architecture §3 S2 failure
handling: "section detection fails -> single body section, flag").
"""

from __future__ import annotations

import re
from collections import Counter

from app.domain.paper import Section

_MAX_HEADING_LINE_LEN = 80

_CANONICAL_HEADINGS = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "motivation",
    "method",
    "methods",
    "methodology",
    "approach",
    "materials and methods",
    "experiments",
    "experimental setup",
    "experimental results",
    "results",
    "evaluation",
    "discussion",
    "conclusion",
    "conclusions",
    "limitations",
    "future work",
    "threats to validity",
    "acknowledgments",
    "acknowledgements",
    "references",
    "bibliography",
    "appendix",
}

# A numbered heading: "1 Introduction", "3.2 Ablations", the equally common
# "1. Introduction" / "3.2. Ablations" style (a period directly after the
# number, observed live in a real paper whose every heading used this
# form -- the earlier pattern required a period-free "1 Introduction", so
# it matched zero headings in that document and section detection fell
# back to one 10-page "Abstract"), or IEEE-style roman numerals -- "I.
# INTRODUCTION", "V. RESULT" (observed live in a second real paper; the
# arabic-only pattern above still matched none of that document's
# headings). Still deliberately excludes headings that end in a period
# (body sentences do; headings don't) via the restricted character class
# with no '.' after the number/heading text.
_NUMBERED_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXLCDM]+\.)\s+[A-Z][A-Za-z0-9,&/'\- ]{1,78}$")


# IEEE (and others) run the label into the paragraph: "Abstract—Public
# transportation...", "Index Terms—GPS, ...". The dash is often lost in
# extraction (U+FFFD) or set as a hyphen, colon or full stop. Such a line
# opens that section; the rest of the line is its first text.
_INLINE_HEADING_RE = re.compile(
    r"^(?P<title>abstract|keywords|key words|index terms)\s*[:.\-\u2013\u2014\ufffd]\s*\S",
    re.IGNORECASE,
)
_INLINE_TITLE = {"abstract": "Abstract", "keywords": "Keywords", "key words": "Keywords", "index terms": "Keywords"}


def _iter_stripped_lines_with_offsets(text: str) -> list[tuple[int, int, str]]:
    """Yield (start, end, stripped_line) for every line, where start/end are
    the offsets of the *stripped* content within `text`."""
    result: list[tuple[int, int, str]] = []
    offset = 0
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if stripped:
            lead_ws = len(raw_line) - len(raw_line.lstrip())
            start = offset + lead_ws
            result.append((start, start + len(stripped), stripped))
        offset += len(raw_line) + 1  # account for the '\n' consumed by split
    return result


def _is_heading(line: str) -> bool:
    if not line or len(line) > _MAX_HEADING_LINE_LEN:
        return False
    normalized = line.rstrip(":").strip().lower()
    if normalized in _CANONICAL_HEADINGS:
        return True
    return bool(_NUMBERED_HEADING_RE.match(line))


def _page_for_offset(offset: int, page_ranges: list[tuple[int, int]]) -> int:
    for i, (start, end) in enumerate(page_ranges, start=1):
        if start <= offset < end:
            return i
    return len(page_ranges) if page_ranges else 1


def _fallback_body_section(full_text: str, page_ranges: list[tuple[int, int]]) -> list[Section]:
    return [
        Section(
            title="Body",
            order=0,
            char_start=0,
            char_end=max(len(full_text), 1),
            page_start=1,
            page_end=len(page_ranges) if page_ranges else 1,
            is_fallback=True,
        )
    ]


def _heading_title(line: str) -> str | None:
    if _is_heading(line):
        return line.rstrip(":").strip()
    inline = _INLINE_HEADING_RE.match(line)
    if inline:
        return _INLINE_TITLE[inline.group("title").lower()]
    return None


# an unnumbered heading word seen this often in one paper is a table's
# column header ("Method", "Results") or a prompt template's field, not a
# section (2026-10-07); a front-matter heading keeps its first, real one
_REPEATED_LABEL = 3
_FRONT_MATTER = {"abstract", "keywords"}


def split_sections(full_text: str, page_ranges: list[tuple[int, int]]) -> list[Section]:
    candidates = [
        (start, title)
        for start, _end, line in _iter_stripped_lines_with_offsets(full_text)
        if (title := _heading_title(line)) is not None
    ]
    unnumbered = Counter(title.lower() for _, title in candidates if not _NUMBERED_HEADING_RE.match(title))
    kept: list[tuple[int, str]] = []
    seen: set[str] = set()
    for start, title in candidates:
        key = title.lower()
        repeated = not _NUMBERED_HEADING_RE.match(title) and unnumbered[key] >= _REPEATED_LABEL
        if repeated and not (key in _FRONT_MATTER and key not in seen):
            continue
        seen.add(key)
        kept.append((start, title))
    candidates = kept

    if len(candidates) < 2:
        return _fallback_body_section(full_text, page_ranges)

    sections: list[Section] = []
    for i, (start, title) in enumerate(candidates):
        end = candidates[i + 1][0] if i + 1 < len(candidates) else len(full_text)
        end = max(end, start + 1)
        sections.append(
            Section(
                title=title,
                order=i,
                char_start=start,
                char_end=end,
                page_start=_page_for_offset(start, page_ranges),
                page_end=_page_for_offset(max(end - 1, start), page_ranges),
            )
        )
    return sections
