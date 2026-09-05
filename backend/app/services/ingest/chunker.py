"""Stage S3: section-aware chunking.

Deterministic. Chunks are built per-section on word boundaries so a chunk
never crosses a section boundary (Architecture §3 S3; a fixed-size
character splitter would fragment scientific context -- review §13). Token
counts are an approximation (words * 1.3) rather than a real tokenizer, to
keep Phase 2 dependency-free and offline-testable; this is documented and
acceptable at the chunk-size granularities used here (see Roadmap Phase 2
acceptance criteria).

Every chunk keeps enough provenance (paper_id, section, page, exact char
offsets into `full_text`) to resolve a claim back to its source span --
this is the data the IEEE-limitation traceability note in
docs/architecture/ResearchNexus_Implementation_Architecture.md §9 depends
on for a future evidence-grounded research-gap workflow.
"""

from __future__ import annotations

import re

from app.config import Settings
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.paper import Section, TableBlock

_WORD_RE = re.compile(r"\S+")
_WORDS_PER_TOKEN = 1.3  # rough English word:BPE-token ratio; see module docstring


def _approx_tokens(word_count: int) -> int:
    return max(1, round(word_count * _WORDS_PER_TOKEN))


def _section_word_spans(section: Section, full_text: str) -> list[tuple[int, int]]:
    section_text = full_text[section.char_start : section.char_end]
    return [(m.start(), m.end()) for m in _WORD_RE.finditer(section_text)]


def _chunk_section_offsets(
    section: Section, full_text: str, target_tokens: int, overlap_tokens: int
) -> list[tuple[int, int, int]]:
    """Return [(global_char_start, global_char_end, approx_token_count), ...]."""
    word_spans = _section_word_spans(section, full_text)
    if not word_spans:
        return []

    target_words = max(1, round(target_tokens / _WORDS_PER_TOKEN))
    overlap_words = min(round(overlap_tokens / _WORDS_PER_TOKEN), target_words - 1) if target_words > 1 else 0

    spans: list[tuple[int, int, int]] = []
    n = len(word_spans)
    start = 0
    while start < n:
        end = min(start + target_words, n)
        char_start = section.char_start + word_spans[start][0]
        char_end = section.char_start + word_spans[end - 1][1]
        spans.append((char_start, char_end, _approx_tokens(end - start)))
        if end == n:
            break
        start = end - overlap_words if overlap_words > 0 else end
    return spans


def _page_for_local_offset(section: Section, local_start: int, section_len: int) -> int:
    if section.page_end <= section.page_start or section_len <= 0:
        return section.page_start
    fraction = local_start / section_len
    page = section.page_start + round(fraction * (section.page_end - section.page_start))
    return max(section.page_start, min(section.page_end, page))


def _anchor_table(table: TableBlock, full_text: str, page_ranges: list[tuple[int, int]]) -> tuple[int, int]:
    """Best-effort provenance for a table: anchor to its caption's location
    in `full_text` when found, else to the start of its page. A table's raw
    cell grid is never itself embedded verbatim in `full_text`, so this is a
    documented approximation, not exact provenance."""
    if table.caption:
        idx = full_text.find(table.caption)
        if idx >= 0:
            return idx, idx + len(table.caption)
    if 1 <= table.page <= len(page_ranges):
        start, end = page_ranges[table.page - 1]
        return start, max(start + 1, min(end, start + 1))
    return 0, 1


def build_chunks(
    paper_id: str,
    full_text: str,
    sections: list[Section],
    tables: list[TableBlock],
    page_ranges: list[tuple[int, int]],
    settings: Settings,
) -> list[PaperChunk]:
    chunks: list[PaperChunk] = []
    counter = 0

    for section in sections:
        kind = ChunkKind.ABSTRACT if section.title.strip().lower() == "abstract" else ChunkKind.BODY
        section_len = section.char_end - section.char_start
        for char_start, char_end, token_count in _chunk_section_offsets(
            section, full_text, settings.chunk_target_tokens, settings.chunk_overlap_tokens
        ):
            text = full_text[char_start:char_end]
            if not text.strip():
                continue
            local_start = char_start - section.char_start
            counter += 1
            chunks.append(
                PaperChunk(
                    chunk_id=f"chk_{paper_id}_{counter}",
                    paper_id=paper_id,
                    section=section.title,
                    section_order=section.order,
                    page=_page_for_local_offset(section, local_start, section_len),
                    char_start=char_start,
                    char_end=char_end,
                    kind=kind,
                    text=text,
                    token_count=token_count,
                )
            )

    for table in tables:
        char_start, char_end = _anchor_table(table, full_text, page_ranges)
        counter += 1
        chunks.append(
            PaperChunk(
                chunk_id=f"chk_{paper_id}_{counter}",
                paper_id=paper_id,
                section=None,
                section_order=None,
                page=table.page,
                char_start=char_start,
                char_end=char_end,
                kind=ChunkKind.TABLE,
                text=table.raw_text,
                token_count=_approx_tokens(len(table.raw_text.split())),
            )
        )

    return chunks
