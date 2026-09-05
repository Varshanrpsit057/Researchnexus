from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.paper import ParseConfidence, ParsedDocument, RawReference, Section, TableBlock
from app.security.pdf_sanitizer import PdfFileMeta


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _sample_parsed_document() -> ParsedDocument:
    return ParsedDocument(
        full_text="1 Introduction\nSome text.\nReferences\n[1] A ref.\n",
        sections=[
            Section(title="1 Introduction", order=0, char_start=0, char_end=25, page_start=1, page_end=1),
            Section(title="References", order=1, char_start=25, char_end=45, page_start=1, page_end=1),
        ],
        tables=[TableBlock(page=1, raw_text="a\tb", caption="Table 1: x", order=0)],
        references=[RawReference(order=0, raw_text="[1] A ref.")],
        page_count=1,
        has_text_layer=True,
        parse_confidence=ParseConfidence.HIGH,
        title="A Sample Paper",
        authors=["A. Author"],
    )


def test_save_and_get_paper_round_trip(db: Session) -> None:
    meta = PdfFileMeta(sha256="a" * 64, size_bytes=1234, page_count=1, has_text_layer=True, encrypted=False)
    parsed = _sample_parsed_document()
    paper = repo.paper_from_ingest(paper_id="pap_1", meta=meta, parsed=parsed, pdf_path="data/papers/pap_1.pdf")
    repo.save_paper(db, paper)

    fetched = repo.get_paper(db, "pap_1")
    assert fetched is not None
    assert fetched.title == "A Sample Paper"
    assert fetched.authors == ["A. Author"]
    assert fetched.pdf_sha256 == "a" * 64
    assert fetched.parse_confidence == "high"
    assert len(fetched.sections) == 2
    assert fetched.sections[0]["title"] == "1 Introduction"
    assert len(fetched.tables) == 1
    assert len(fetched.references) == 1


def test_find_paper_by_sha256(db: Session) -> None:
    meta = PdfFileMeta(sha256="b" * 64, size_bytes=1, page_count=1, has_text_layer=True, encrypted=False)
    paper = repo.paper_from_ingest("pap_2", meta, _sample_parsed_document(), "path.pdf")
    repo.save_paper(db, paper)

    found = repo.find_paper_by_sha256(db, "b" * 64)
    assert found is not None
    assert found.id == "pap_2"
    assert repo.find_paper_by_sha256(db, "c" * 64) is None


def test_save_and_get_chunks_round_trip(db: Session) -> None:
    meta = PdfFileMeta(sha256="d" * 64, size_bytes=1, page_count=1, has_text_layer=True, encrypted=False)
    paper = repo.paper_from_ingest("pap_3", meta, _sample_parsed_document(), "path.pdf")
    repo.save_paper(db, paper)

    chunks = [
        PaperChunk(
            chunk_id="chk_1",
            paper_id="pap_3",
            section="1 Introduction",
            section_order=0,
            page=1,
            char_start=0,
            char_end=10,
            kind=ChunkKind.BODY,
            text="Some text.",
            token_count=2,
        ),
        PaperChunk(
            chunk_id="chk_2",
            paper_id="pap_3",
            section=None,
            section_order=None,
            page=1,
            char_start=20,
            char_end=25,
            kind=ChunkKind.TABLE,
            text="a\tb",
            token_count=1,
        ),
    ]
    repo.save_chunks(db, chunks)

    fetched = repo.get_chunks_for_paper(db, "pap_3")
    assert len(fetched) == 2
    assert fetched[0].chunk_id == "chk_1"
    assert fetched[0].kind == ChunkKind.BODY
    assert fetched[1].kind == ChunkKind.TABLE
    assert fetched[1].text == "a\tb"


def test_job_lifecycle(db: Session) -> None:
    job = Job(job_id="job_1", owner_id="usr_dev", workspace_id=None, kind=JobKind.INGEST)
    repo.create_job(db, job)

    fetched = repo.get_job(db, "job_1")
    assert fetched is not None
    assert fetched.status == JobStatus.QUEUED

    repo.update_job(db, "job_1", status=JobStatus.RUNNING, progress={"parse": "running"})
    running = repo.get_job(db, "job_1")
    assert running is not None
    assert running.status == JobStatus.RUNNING
    assert running.progress == {"parse": "running"}

    repo.update_job(db, "job_1", status=JobStatus.SUCCEEDED, result_ref="pap_1")
    done = repo.get_job(db, "job_1")
    assert done is not None
    assert done.status == JobStatus.SUCCEEDED
    assert done.result_ref == "pap_1"
    assert done.error is None


def test_update_job_missing_id_returns_none(db: Session) -> None:
    assert repo.update_job(db, "does-not-exist", status=JobStatus.FAILED) is None
    assert repo.get_job(db, "does-not-exist") is None
