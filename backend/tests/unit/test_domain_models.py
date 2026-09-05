"""Domain model contracts for Phase 2 (PDF ingestion).

These mirror docs/architecture/ResearchNexus_Data_Model.md (PaperChunk, Job)
and docs/architecture/ResearchNexus_Implementation_Architecture.md §3 (S2
ParsedDocument / Section / TableBlock / RawReference).
"""

import pytest
from pydantic import ValidationError

from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.paper import (
    ParseConfidence,
    ParsedDocument,
    RawReference,
    Section,
    TableBlock,
)


class TestSection:
    def test_valid_section(self) -> None:
        s = Section(title="1 Introduction", order=1, char_start=0, char_end=100, page_start=1, page_end=2)
        assert s.title == "1 Introduction"
        assert s.char_end > s.char_start

    def test_char_end_must_be_after_char_start(self) -> None:
        with pytest.raises(ValidationError):
            Section(title="Body", order=0, char_start=50, char_end=10, page_start=1, page_end=1)


class TestTableBlock:
    def test_defaults(self) -> None:
        t = TableBlock(page=3, raw_text="a\tb\n1\t2")
        assert t.caption is None
        assert t.page == 3


class TestRawReference:
    def test_order_and_text(self) -> None:
        r = RawReference(order=1, raw_text="A. Author, 'A paper', 2020.")
        assert r.order == 1
        assert "Author" in r.raw_text


class TestParsedDocument:
    def test_single_fallback_section_when_none_detected(self) -> None:
        doc = ParsedDocument(
            full_text="hello world",
            sections=[Section(title="Body", order=0, char_start=0, char_end=11, page_start=1, page_end=1)],
            tables=[],
            references=[],
            page_count=1,
            has_text_layer=True,
            parse_confidence=ParseConfidence.LOW,
        )
        assert len(doc.sections) == 1
        assert doc.sections[0].title == "Body"

    def test_parse_confidence_is_enum(self) -> None:
        with pytest.raises(ValidationError):
            ParsedDocument(
                full_text="x",
                sections=[],
                tables=[],
                references=[],
                page_count=1,
                has_text_layer=True,
                parse_confidence="not-a-level",  # type: ignore[arg-type]
            )


class TestPaperChunk:
    def test_valid_chunk(self) -> None:
        c = PaperChunk(
            chunk_id="chk_1",
            paper_id="pap_1",
            section="1 Introduction",
            section_order=1,
            page=1,
            char_start=0,
            char_end=120,
            kind=ChunkKind.BODY,
            text="Some scientific text.",
            token_count=4,
        )
        assert c.workspace_id is None
        assert c.kind == ChunkKind.BODY

    def test_char_range_validated(self) -> None:
        with pytest.raises(ValidationError):
            PaperChunk(
                chunk_id="chk_1",
                paper_id="pap_1",
                section=None,
                section_order=None,
                page=None,
                char_start=10,
                char_end=5,
                kind=ChunkKind.BODY,
                text="x",
                token_count=1,
            )

    def test_empty_text_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PaperChunk(
                chunk_id="chk_1",
                paper_id="pap_1",
                section=None,
                section_order=None,
                page=None,
                char_start=0,
                char_end=1,
                kind=ChunkKind.BODY,
                text="   ",
                token_count=0,
            )


class TestJob:
    def test_defaults(self) -> None:
        j = Job(job_id="job_1", owner_id="usr_dev", workspace_id=None, kind=JobKind.INGEST)
        assert j.status == JobStatus.QUEUED
        assert j.progress == {}
        assert j.result_ref is None
        assert j.error is None
