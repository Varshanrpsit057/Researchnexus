from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.domain.paper import ParseConfidence
from app.services.ingest.pdf_loader import LoadedPage
from app.services.ingest.pipeline import _fallback_title, run_ingestion


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]


def test_run_ingestion_persists_paper_and_chunks(
    db: Session, settings: Settings, normal_paper_pdf_bytes: bytes
) -> None:
    result = run_ingestion(db, "pap_normal", normal_paper_pdf_bytes, "paper.pdf", settings)

    assert result.deduplicated is False
    assert result.chunk_count > 0
    assert result.parse_confidence in (ParseConfidence.HIGH, ParseConfidence.MEDIUM)

    paper = repo.get_paper(db, "pap_normal")
    assert paper is not None
    assert "Retrieval-Augmented Generation" in paper.title
    assert paper.has_full_text is True
    assert len(paper.sections) >= 4
    assert len(paper.tables) >= 1
    assert len(paper.references) == 5

    chunks = repo.get_chunks_for_paper(db, "pap_normal")
    assert len(chunks) == result.chunk_count

    stored_pdf = settings.pdf_storage_dir() / "pap_normal.pdf"
    assert stored_pdf.exists()
    assert stored_pdf.read_bytes() == normal_paper_pdf_bytes


def test_run_ingestion_is_idempotent_by_content_hash(
    db: Session, settings: Settings, normal_paper_pdf_bytes: bytes
) -> None:
    first = run_ingestion(db, "pap_A", normal_paper_pdf_bytes, "paper.pdf", settings)
    assert first.deduplicated is False

    second = run_ingestion(db, "pap_B", normal_paper_pdf_bytes, "paper-copy.pdf", settings)
    assert second.deduplicated is True
    assert second.paper_id == "pap_A"

    assert repo.get_paper(db, "pap_B") is None
    assert repo.get_paper(db, "pap_A") is not None


def test_run_ingestion_flags_low_confidence_without_headings(
    db: Session, settings: Settings, multi_page_pdf_factory
) -> None:
    data = multi_page_pdf_factory(2)
    result = run_ingestion(db, "pap_plain", data, "plain.pdf", settings)

    assert result.parse_confidence == ParseConfidence.LOW
    paper = repo.get_paper(db, "pap_plain")
    assert paper is not None
    assert paper.sections[0]["title"] == "Body"
    assert paper.sections[0]["is_fallback"] is True


def test_run_ingestion_two_column_paper_produces_chunks_and_body_text(
    db: Session, settings: Settings, two_column_paper_pdf_bytes: bytes
) -> None:
    result = run_ingestion(db, "pap_2col", two_column_paper_pdf_bytes, "two_col.pdf", settings)
    assert result.chunk_count > 0
    chunks = repo.get_chunks_for_paper(db, "pap_2col")
    joined = " ".join(c.text for c in chunks)
    assert "INTROSTART" in joined
    assert "METHODSTART" in joined


def _page(text: str) -> list[LoadedPage]:
    return [LoadedPage(number=1, text=text)]


def test_fallback_title_skips_publisher_running_header() -> None:
    # Observed live: a real ScienceDirect PDF stamps this exact running
    # header on page 1, ahead of the real title -- a naive "first
    # reasonably long line" picked the header instead of the paper.
    text = (
        "Available online at www.sciencedirect.com\n"
        "ScienceDirect\n"
        "Procedia Computer Science 258 (2025) 3031-3041\n"
        "www.elsevier.com/locate/procedia\n"
        "A Study of Retrieval Augmented Generation for Long Documents\n"
        "A. Author, B. Coauthor\n"
    )
    assert _fallback_title(_page(text)) == "A Study of Retrieval Augmented Generation for Long Documents"


def test_fallback_title_skips_conference_name_line() -> None:
    # Conference proceedings print the event name directly above the
    # paper's own title -- a phrasing no paper title itself uses.
    text = (
        "International Conference on Machine Learning and Data Engineering\n"
        "Enhancing Classroom Attendance Systems with Face Recognition\n"
        "J. Patel, S. Gandhi\n"
    )
    assert _fallback_title(_page(text)) == "Enhancing Classroom Attendance Systems with Face Recognition"


def test_fallback_title_skips_digit_heavy_garbled_line() -> None:
    # A line thick with stray digits/symbols (e.g. a mis-extracted,
    # overlapping-text watermark) is not plausible prose for a title.
    text = (
        "AvaiPlarobcleed ioan Clionmep autte wr Swciwen i0e0n (c2e02d5ir)e 0c0t0\n"
        "A Clean and Readable Paper Title Goes Here\n"
    )
    assert _fallback_title(_page(text)) == "A Clean and Readable Paper Title Goes Here"


def test_fallback_title_merges_a_wrapped_second_line() -> None:
    # A long title commonly wraps onto a second PDF line before the author
    # list starts. The continuation line must be title-shaped and
    # comma-free (an author byline always has commas).
    text = (
        "Enhancing Classroom Attendance Systems with Face Recognition\n"
        "through CCTV using Deep Learning\n"
        "Jaykumar Patel, Savita Gandhi, Vishal Katheriya\n"
    )
    assert _fallback_title(_page(text)) == (
        "Enhancing Classroom Attendance Systems with Face Recognition through CCTV using Deep Learning"
    )


def test_fallback_title_merges_more_than_one_wrapped_line() -> None:
    # Observed live: a real 3-line title ("REAL-TIME STUDENT ATTENDANCE" /
    # "SYSTEM USING FACE RECOGNITION AND" / "CLOUD INTEGRATION") was cut off
    # mid-phrase when only a single continuation line was merged.
    text = (
        "REAL-TIME STUDENT ATTENDANCE\n"
        "SYSTEM USING FACE RECOGNITION AND\n"
        "CLOUD INTEGRATION\n"
        "Gowthaman S, Harrish Sridhar, Sreeman T S\n"
    )
    assert _fallback_title(_page(text)) == (
        "REAL-TIME STUDENT ATTENDANCE SYSTEM USING FACE RECOGNITION AND CLOUD INTEGRATION"
    )


def test_fallback_title_does_not_merge_an_author_byline() -> None:
    # The author line has commas, so it must not be swallowed into the title.
    text = (
        "A Short and Complete Title\n"
        "Jaykumar Patel, Savita Gandhi, Vishal Katheriya\n"
    )
    assert _fallback_title(_page(text)) == "A Short and Complete Title"


def test_fallback_title_returns_none_when_no_candidate_line_exists() -> None:
    text = "www.sciencedirect.com\nScienceDirect\n123 (2020) 1-2\n"
    assert _fallback_title(_page(text)) is None
