from __future__ import annotations

from app.domain.chunk import ChunkKind, PaperChunk
from app.services.profile.context_selector import render_context, select_context_chunks


def _chunk(section: str | None, text: str, char_start: int, kind: ChunkKind = ChunkKind.BODY) -> PaperChunk:
    return PaperChunk(
        chunk_id=f"chk_{char_start}",
        paper_id="pap_1",
        section=section,
        section_order=0,
        page=1,
        char_start=char_start,
        char_end=char_start + len(text),
        kind=kind,
        text=text,
        token_count=len(text.split()),
    )


def test_selects_only_target_sections_in_document_order() -> None:
    chunks = [
        _chunk("Abstract", "abstract text", 0, ChunkKind.ABSTRACT),
        _chunk("1 Introduction", "intro text", 20),
        _chunk("References", "reference list", 40),
        _chunk("3 Method", "method text", 60),
    ]
    selected = select_context_chunks(chunks, max_chars=10_000)
    sections = [c.section for c in selected]
    assert sections == ["Abstract", "1 Introduction", "3 Method"]


def test_excludes_table_chunks() -> None:
    chunks = [
        _chunk("Abstract", "abstract text", 0, ChunkKind.ABSTRACT),
        _chunk(None, "raw table grid", 20, ChunkKind.TABLE),
    ]
    selected = select_context_chunks(chunks, max_chars=10_000)
    assert all(c.kind != ChunkKind.TABLE for c in selected)


def test_fallback_body_section_includes_everything_up_to_budget() -> None:
    chunks = [_chunk("Body", "x" * 100, 0), _chunk("Body", "y" * 100, 200)]
    selected = select_context_chunks(chunks, max_chars=10_000)
    assert len(selected) == 2


def test_respects_char_budget() -> None:
    chunks = [
        _chunk("Abstract", "a" * 100, 0, ChunkKind.ABSTRACT),
        _chunk("1 Introduction", "b" * 100, 200),
        _chunk("3 Method", "c" * 100, 400),
    ]
    selected = select_context_chunks(chunks, max_chars=150)
    assert len(selected) == 1
    assert selected[0].section == "Abstract"


def test_render_context_includes_section_and_page_headers() -> None:
    chunks = [_chunk("Abstract", "abstract text", 0, ChunkKind.ABSTRACT)]
    text = render_context(chunks)
    assert "Abstract" in text
    assert "abstract text" in text


def test_render_context_empty_list_returns_empty_string() -> None:
    assert render_context([]) == ""
