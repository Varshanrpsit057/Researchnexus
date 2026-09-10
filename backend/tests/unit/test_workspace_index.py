from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.domain.candidate import NormalizedCandidate
from app.domain.chunk import ChunkKind, PaperChunk
from app.retrieval.workspace_index import DbBackedWorkspaceIndex, load_manifest
from app.services.normalize.canonical import title_hash


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(conn: object, _rec: object) -> None:
        cur = conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _paper_with_chunks(db: Session, title: str, texts: list[str]) -> str:
    pid = repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title)))
    chunks = [
        PaperChunk(
            chunk_id=f"chk_{pid}_{i}",
            paper_id=pid,
            section="body",
            char_start=i * 100,
            char_end=i * 100 + len(t),
            kind=ChunkKind.BODY,
            text=t,
            token_count=len(t.split()),
        )
        for i, t in enumerate(texts)
    ]
    repo.save_chunks(db, chunks)
    return pid


def test_rebuild_indexes_only_member_papers(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval for question answering", "reranking with cross encoders"])
    b = _paper_with_chunks(db, "B", ["graph neural networks for molecules"])
    _paper_with_chunks(db, "C outside", ["unrelated text about databases"])

    idx = DbBackedWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    manifest = idx.rebuild([a, b])

    assert set(idx.paper_ids()) == {a, b}
    assert manifest.chunk_count == 3
    assert manifest.workspace_id == "ws_1"


def test_search_ranks_by_lexical_overlap_and_respects_k(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval for open domain question answering", "unrelated cooking recipe"])
    b = _paper_with_chunks(db, "B", ["cross encoder reranking improves retrieval"])
    idx = DbBackedWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    idx.rebuild([a, b])

    hits = idx.search("retrieval question answering", k=2)
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
    assert all(h.paper_id in {a, b} for h in hits)
    assert "retrieval" in hits[0].text or "retrieval" in hits[1].text


def test_add_paper_makes_its_chunks_searchable(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval"])
    b = _paper_with_chunks(db, "B", ["contrastive pretraining of sentence embeddings"])
    idx = DbBackedWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    idx.rebuild([a])
    assert idx.search("contrastive pretraining", k=5) == []

    manifest = idx.add_paper(b)
    assert set(idx.paper_ids()) == {a, b}
    assert manifest.chunk_count == 2
    assert any("contrastive" in h.text for h in idx.search("contrastive pretraining", k=5))


def test_remove_paper_evicts_its_chunks_from_search(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval for question answering"])
    b = _paper_with_chunks(db, "B", ["dense retrieval with hard negatives"])
    idx = DbBackedWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    idx.rebuild([a, b])
    assert {h.paper_id for h in idx.search("dense retrieval", k=10)} == {a, b}

    idx.remove_paper(b)
    hits = idx.search("dense retrieval", k=10)
    assert {h.paper_id for h in hits} == {a}
    assert b not in idx.paper_ids()
    assert idx.manifest().chunk_count == 1


def test_adding_a_paper_with_no_chunks_is_a_noop(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval"])
    empty = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Empty", title_hash=title_hash("Empty")))
    idx = DbBackedWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    idx.rebuild([a])
    manifest = idx.add_paper(empty)
    assert empty in idx.paper_ids()
    assert manifest.chunk_count == 1


def test_manifest_is_persisted_and_reloadable(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval", "cross encoder"])
    idx = DbBackedWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    manifest = idx.rebuild([a])

    assert manifest.index_path is not None
    on_disk = Path(manifest.index_path)
    assert on_disk.exists()
    payload = json.loads(on_disk.read_text())
    assert payload["workspace_id"] == "ws_1"
    assert payload["paper_ids"] == [a]

    reloaded = load_manifest(tmp_path, "ws_1")
    assert reloaded is not None
    assert reloaded.paper_ids == [a]
    assert reloaded.chunk_count == 2


def test_rebuild_is_deterministic(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval for question answering", "reranking"])
    b = _paper_with_chunks(db, "B", ["retrieval augmented generation"])
    idx = DbBackedWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)

    m1 = idx.rebuild([a, b])
    order1 = [h.chunk_id for h in idx.search("retrieval", k=10)]
    score1 = [round(h.score, 6) for h in idx.search("retrieval", k=10)]
    m2 = idx.rebuild([a, b])
    order2 = [h.chunk_id for h in idx.search("retrieval", k=10)]
    score2 = [round(h.score, 6) for h in idx.search("retrieval", k=10)]

    assert m1.model_dump(exclude={"built_at", "index_path"}) == m2.model_dump(exclude={"built_at", "index_path"})
    assert order1 == order2
    assert score1 == score2
    # membership order is caller-defined and preserved verbatim
    assert idx.rebuild([b, a]).paper_ids == [b, a]
