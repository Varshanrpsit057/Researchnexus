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
from app.services.ingest.pipeline import run_ingestion


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
