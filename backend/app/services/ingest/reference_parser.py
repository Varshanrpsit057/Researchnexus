"""Stage S2 (part 5): segment the References/Bibliography section.

Deterministic. Full citation parsing (authors/year/DOI extraction) is out
of scope for Phase 2 -- this only preserves each entry's raw text and order
so later phases can resolve it against Crossref/OpenAlex/arXiv (citation
edges, contradiction evidence). See the IEEE-limitation traceability note
in docs/architecture/ResearchNexus_Implementation_Architecture.md §9.
"""

from __future__ import annotations

import re

from app.domain.paper import RawReference, Section

_BRACKET_MARKER_RE = re.compile(r"^\[(\d+)\]\s*")
_NUMBER_DOT_MARKER_RE = re.compile(r"^(\d+)\.\s+")
_REFERENCE_SECTION_TITLES = {"references", "bibliography"}


def _find_references_section(sections: list[Section]) -> Section | None:
    for s in sections:
        if s.title.strip().lower() in _REFERENCE_SECTION_TITLES:
            return s
    return None


def _marker_line_indices(lines: list[str], pattern: re.Pattern[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if pattern.match(line.strip())]


def parse_references(full_text: str, sections: list[Section]) -> list[RawReference]:
    section = _find_references_section(sections)
    if section is None:
        return []

    body = full_text[section.char_start : section.char_end]
    lines = body.split("\n")
    if lines and lines[0].strip() == section.title:
        lines = lines[1:]

    bracket_hits = _marker_line_indices(lines, _BRACKET_MARKER_RE)
    number_dot_hits = _marker_line_indices(lines, _NUMBER_DOT_MARKER_RE)

    if len(bracket_hits) >= 2:
        marker_lines = bracket_hits
    elif len(number_dot_hits) >= 2:
        marker_lines = number_dot_hits
    else:
        marker_lines = []

    entries: list[str] = []
    if marker_lines:
        for idx, start in enumerate(marker_lines):
            end = marker_lines[idx + 1] if idx + 1 < len(marker_lines) else len(lines)
            block = " ".join(line.strip() for line in lines[start:end] if line.strip())
            entries.append(block)
    else:
        blocks: list[list[str]] = [[]]
        for line in lines:
            if line.strip() == "":
                if blocks[-1]:
                    blocks.append([])
            else:
                blocks[-1].append(line.strip())
        entries = [" ".join(b) for b in blocks if b]

    non_empty = [e.strip() for e in entries if e.strip()]
    return [RawReference(order=i, raw_text=e) for i, e in enumerate(non_empty)]
