"""Deterministic provenance resolution: turn an LLM-proposed (value, quote)
pair into a real `SourceSpan` with a verified/unverified status by locating
the quote in the paper's own persisted chunk text (Architecture §2: "Profile
provenance check (span exists in text) -- Deterministic -- catches
hallucinated fields"). No LLM call happens here.

Fuzzy matching uses the standard library's `difflib` rather than the
`rapidfuzz` dependency the Roadmap names for this ("Dependencies. rapidfuzz
(span matching)"): the exact same "quote fuzzy-matches ratio >= 0.9" rule
(Data Model §2) is achievable with `SequenceMatcher`, so no new dependency
is added (CLAUDE.md: prefer the standard library).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.domain.chunk import PaperChunk
from app.domain.profile import ProfileField, ProfileList, ProvenanceStatus, SourceSpan
from app.llm.prompts.profile_v1 import ExtractedField, ExtractedList

_FUZZY_MATCH_THRESHOLD = 0.9
_MAX_QUOTE_LEN = 400
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_ws(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _partial_ratio(needle: str, haystack: str) -> float:
    """Approximates rapidfuzz's `partial_ratio` using only the standard
    library: what fraction of `needle`'s characters find an in-order match
    somewhere in `haystack`, independent of `haystack`'s own length (a plain
    `SequenceMatcher.ratio()` over the full strings would unfairly penalise
    a short quote sitting inside a much longer chunk)."""
    if not needle:
        return 0.0
    matcher = SequenceMatcher(None, needle, haystack, autojunk=False)
    matched_chars = sum(block.size for block in matcher.get_matching_blocks())
    return matched_chars / len(needle)


def resolve_field(paper_id: str, extracted: ExtractedField, chunks: list[PaperChunk]) -> ProfileField:
    value = extracted.value.strip()
    quote = (extracted.quote or "").strip()
    if not quote:
        return ProfileField(value=value, source_span=None, status=ProvenanceStatus.UNVERIFIED)

    for chunk in chunks:
        idx = chunk.text.find(quote)
        if idx >= 0:
            span = SourceSpan(
                paper_id=paper_id,
                section=chunk.section,
                page=chunk.page,
                char_start=chunk.char_start + idx,
                char_end=chunk.char_start + idx + len(quote),
                quote=quote[:_MAX_QUOTE_LEN],
            )
            return ProfileField(value=value, source_span=span, status=ProvenanceStatus.VERIFIED)

    normalized_quote = _normalize_ws(quote)
    best_ratio = 0.0
    best_chunk: PaperChunk | None = None
    for chunk in chunks:
        ratio = _partial_ratio(normalized_quote, _normalize_ws(chunk.text))
        if ratio > best_ratio:
            best_ratio, best_chunk = ratio, chunk

    if best_chunk is not None and best_ratio >= _FUZZY_MATCH_THRESHOLD:
        span = SourceSpan(
            paper_id=paper_id,
            section=best_chunk.section,
            page=best_chunk.page,
            char_start=best_chunk.char_start,
            char_end=best_chunk.char_end,
            quote=quote[:_MAX_QUOTE_LEN],
        )
        return ProfileField(value=value, source_span=span, status=ProvenanceStatus.VERIFIED)

    return ProfileField(value=value, source_span=None, status=ProvenanceStatus.UNVERIFIED)


def resolve_list(paper_id: str, extracted: ExtractedList, chunks: list[PaperChunk]) -> ProfileList:
    return ProfileList(
        items=[resolve_field(paper_id, item, chunks) for item in extracted.items if item.value.strip()]
    )
