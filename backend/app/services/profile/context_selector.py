"""Deterministic selection of which paper text to show the LLM for profile
extraction (Architecture §3 S4: "In: ParsedDocument (abstract + intro +
method + experiments + conclusion + any Limitations/Future Work)"). Picking
sections is a rule, not a judgement call, so it stays out of the one LLM
call this stage makes (Architecture §2: the LLM layer must not "make
relevance judgements that aren't rule-expressible").

Table chunks are deliberately excluded -- S4's documented input is prose
sections, not raw table grids (see app/services/ingest/table_extractor.py
for how tables are captured; they feed Phase 11's future gap matrix, not
this prompt).
"""

from __future__ import annotations

import re

from app.domain.chunk import ChunkKind, PaperChunk

# Numbered headings ("1 Introduction", "3.2 Ablations") carry a leading
# number that isn't part of the canonical name -- strip it before matching
# (mirrors the heading shapes app/services/ingest/section_splitter.py itself
# recognises).
_LEADING_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*\s+")

_TARGET_SECTION_NAMES = {
    "abstract",
    "body",  # the single fallback section when no real headings were found
    "introduction",
    "background",
    "motivation",
    "related work",
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
}


def _normalize_heading(title: str) -> str:
    return _LEADING_NUMBER_RE.sub("", title.strip()).lower()


def select_context_chunks(chunks: list[PaperChunk], max_chars: int) -> list[PaperChunk]:
    """Chunks are returned in document order, non-table, restricted to the
    sections judged relevant to profile extraction, truncated to a char
    budget (a coarse stand-in for a token budget -- see
    app/services/ingest/chunker.py's own words*1.3 approximation for the
    same "no tokenizer dependency" rationale)."""
    ordered = sorted(chunks, key=lambda c: c.char_start)
    candidates = [
        c
        for c in ordered
        if c.kind != ChunkKind.TABLE and c.section is not None and _normalize_heading(c.section) in _TARGET_SECTION_NAMES
    ]
    if not candidates:
        candidates = [c for c in ordered if c.kind != ChunkKind.TABLE]

    selected: list[PaperChunk] = []
    total = 0
    for chunk in candidates:
        # Always include at least one chunk, even if it alone exceeds the
        # budget, so a paper whose first relevant section is long never
        # yields an empty context; every chunk after that must fit.
        if selected and total + len(chunk.text) > max_chars:
            break
        selected.append(chunk)
        total += len(chunk.text)
    return selected


def render_context(chunks: list[PaperChunk]) -> str:
    parts = [f"[section: {c.section or 'unknown'} | page: {c.page or '?'}]\n{c.text}" for c in chunks]
    return "\n\n".join(parts)
