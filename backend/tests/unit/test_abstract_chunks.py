from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM
from app.domain.candidate import NormalizedCandidate
from app.domain.chunk import ChunkKind
from app.services.ingest.abstract_chunks import abstract_chunk_id, ensure_abstract_chunks
from app.services.normalize.canonical import title_hash


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _discovered(db: Session, title: str, abstract: str | None) -> str:
    return repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title), abstract=abstract))


def test_an_abstract_only_paper_gets_its_abstract_as_one_chunk(db: Session) -> None:
    pid = _discovered(db, "Late interaction", "  We propose a late-interaction reranker.  ")
    assert ensure_abstract_chunks(db, [pid]) == 1
    [chunk] = repo.get_chunks_for_paper(db, pid)
    assert chunk.chunk_id == abstract_chunk_id(pid)
    assert (chunk.section, chunk.kind, chunk.text) == ("Abstract", ChunkKind.ABSTRACT, "We propose a late-interaction reranker.")
    assert (chunk.char_start, chunk.char_end, chunk.token_count) == (0, len(chunk.text), 5)


def test_it_is_idempotent_and_leaves_other_papers_alone(db: Session) -> None:
    pid = _discovered(db, "Late interaction", "We propose a late-interaction reranker.")
    no_abstract = _discovered(db, "Title only", None)
    repo.save_paper(db, PaperORM(id="pap_pdf", title="Uploaded", title_hash=title_hash("uploaded"), has_full_text=True, abstract="has a pdf"))
    assert ensure_abstract_chunks(db, [pid, no_abstract, "pap_pdf", "pap_missing"]) == 1
    assert ensure_abstract_chunks(db, [pid, pid]) == 0
    assert repo.get_chunks_for_paper(db, no_abstract) == []
    assert repo.get_chunks_for_paper(db, "pap_pdf") == []  # full text is the PDF chunker's job
