from __future__ import annotations

from app.config import Settings
from app.domain.chunk import ChunkKind
from app.domain.paper import Section, TableBlock
from app.services.ingest.chunker import build_chunks
from app.services.ingest.cleaner import clean_pages
from app.services.ingest.pdf_loader import load_pdf
from app.services.ingest.reference_parser import parse_references
from app.services.ingest.section_splitter import split_sections
from app.services.ingest.table_extractor import extract_table_blocks

_WORDY_TEXT = "word " * 400  # ~400 words, enough to force multiple chunks at small targets


def _tiny_settings(target_tokens: int = 20, overlap_tokens: int = 5) -> Settings:
    return Settings(_env_file=None, chunk_target_tokens=target_tokens, chunk_overlap_tokens=overlap_tokens)  # type: ignore[call-arg]


def test_chunks_never_cross_section_boundaries() -> None:
    sec_a_text = "alpha " * 200
    sec_b_text = "beta " * 200
    full_text = sec_a_text + sec_b_text
    sections = [
        Section(title="1 A", order=0, char_start=0, char_end=len(sec_a_text), page_start=1, page_end=1),
        Section(
            title="2 B",
            order=1,
            char_start=len(sec_a_text),
            char_end=len(full_text),
            page_start=1,
            page_end=1,
        ),
    ]
    settings = _tiny_settings()
    chunks = build_chunks("pap_1", full_text, sections, tables=[], page_ranges=[(0, len(full_text))], settings=settings)
    assert len(chunks) > 2  # forced multiple chunks per section
    for c in chunks:
        section = sections[c.section_order]  # type: ignore[index]
        assert section.char_start <= c.char_start
        assert c.char_end <= section.char_end
        assert "alpha" not in c.text or "beta" not in c.text  # never mixes both sections


def test_consecutive_chunks_in_same_section_overlap() -> None:
    section = Section(title="1 A", order=0, char_start=0, char_end=len(_WORDY_TEXT), page_start=1, page_end=1)
    chunks = build_chunks(
        "pap_1", _WORDY_TEXT, [section], tables=[], page_ranges=[(0, len(_WORDY_TEXT))], settings=_tiny_settings()
    )
    assert len(chunks) >= 3
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start < a.char_end  # overlap


def test_short_section_produces_a_single_chunk() -> None:
    text = "This is a short section with only a handful of words."
    section = Section(title="1 A", order=0, char_start=0, char_end=len(text), page_start=1, page_end=1)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # default target 750 tokens
    chunks = build_chunks("pap_1", text, [section], tables=[], page_ranges=[(0, len(text))], settings=settings)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].kind == ChunkKind.BODY


def test_abstract_section_gets_abstract_kind() -> None:
    text = "This paper studies retrieval augmented generation for scientific papers."
    section = Section(title="Abstract", order=0, char_start=0, char_end=len(text), page_start=1, page_end=1)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    chunks = build_chunks("pap_1", text, [section], tables=[], page_ranges=[(0, len(text))], settings=settings)
    assert chunks[0].kind == ChunkKind.ABSTRACT


def test_table_becomes_its_own_chunk_anchored_to_caption() -> None:
    full_text = "1 A\nsome text\nTable 1: results\nmore text\n"
    table = TableBlock(page=1, raw_text="Method\tF1\nBM25\t42.1", caption="Table 1: results", order=0)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    chunks = build_chunks(
        "pap_1", full_text, sections=[], tables=[table], page_ranges=[(0, len(full_text))], settings=settings
    )
    assert len(chunks) == 1
    c = chunks[0]
    assert c.kind == ChunkKind.TABLE
    assert c.text == table.raw_text
    assert full_text[c.char_start : c.char_end] == "Table 1: results"


def test_all_non_table_chunks_round_trip_to_full_text() -> None:
    section = Section(title="1 A", order=0, char_start=0, char_end=len(_WORDY_TEXT), page_start=1, page_end=3)
    chunks = build_chunks(
        "pap_1", _WORDY_TEXT, [section], tables=[], page_ranges=[(0, len(_WORDY_TEXT))], settings=_tiny_settings()
    )
    for c in chunks:
        assert _WORDY_TEXT[c.char_start : c.char_end] == c.text
        assert section.page_start <= c.page <= section.page_end  # type: ignore[operator]


def test_real_fixture_end_to_end_chunking(normal_paper_pdf_bytes: bytes) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    raw = load_pdf(normal_paper_pdf_bytes, settings)
    cleaned_pages, full_text, ranges = clean_pages([p.text for p in raw.pages])
    sections = split_sections(full_text, ranges)
    tables = extract_table_blocks(raw.pages, cleaned_pages)
    references = parse_references(full_text, sections)
    assert references  # sanity: fixture has a references section

    chunks = build_chunks("pap_real", full_text, sections, tables, ranges, settings)
    assert len(chunks) >= len(sections)
    table_chunks = [c for c in chunks if c.kind == ChunkKind.TABLE]
    assert len(table_chunks) == len(tables)
    for c in chunks:
        if c.kind != ChunkKind.TABLE:
            assert full_text[c.char_start : c.char_end] == c.text
        assert 1 <= c.page <= raw.page_count  # type: ignore[operator]
