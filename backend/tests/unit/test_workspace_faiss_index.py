from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.domain.candidate import NormalizedCandidate
from app.domain.chunk import ChunkKind, PaperChunk
from app.retrieval.workspace_index import (
    FaissWorkspaceIndex,
    WorkspaceIndexCache,
    get_workspace_index,
)
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
    repo.save_chunks(
        db,
        [
            PaperChunk(
                chunk_id=f"chk_{pid}_{i}",
                paper_id=pid,
                section="Methods",
                page=i + 1,
                char_start=i * 100,
                char_end=i * 100 + len(t),
                kind=ChunkKind.BODY,
                text=t,
                token_count=len(t.split()),
            )
            for i, t in enumerate(texts)
        ],
    )
    return pid


def test_build_search_and_membership(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval for question answering", "a cooking recipe"])
    b = _paper_with_chunks(db, "B", ["cross encoder reranking of passages"])
    _paper_with_chunks(db, "C", ["completely unrelated material"])

    idx = FaissWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    manifest = idx.rebuild([a, b])
    assert set(idx.paper_ids()) == {a, b}
    assert manifest.chunk_count == 3

    hits = idx.search("dense retrieval question answering", k=3)
    assert 1 <= len(hits) <= 3
    assert all(h.paper_id in {a, b} for h in hits)
    assert hits == sorted(hits, key=lambda h: (-h.score, h.chunk_id))


def test_add_and_remove_paper_update_search(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval"])
    b = _paper_with_chunks(db, "B", ["graph contrastive pretraining"])
    idx = FaissWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    idx.rebuild([a])

    idx.add_paper(b)
    assert set(idx.paper_ids()) == {a, b}
    assert any(h.paper_id == b for h in idx.search("graph contrastive pretraining", k=5))

    idx.remove_paper(b)
    assert idx.paper_ids() == [a]
    assert all(h.paper_id != b for h in idx.search("graph contrastive pretraining", k=5))
    assert idx.manifest().chunk_count == 1


def test_index_persists_and_loads_without_reembedding(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval", "cross encoder"])
    built = FaissWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path)
    built.rebuild([a])
    before = [(h.chunk_id, round(h.score, 5)) for h in built.search("dense retrieval", k=5)]

    reloaded = FaissWorkspaceIndex.load(db, workspace_id="ws_1", index_dir=tmp_path)
    assert reloaded is not None
    assert reloaded.paper_ids() == [a]
    after = [(h.chunk_id, round(h.score, 5)) for h in reloaded.search("dense retrieval", k=5)]
    assert before == after


def test_embedding_and_search_are_deterministic(db: Session, tmp_path: Path) -> None:
    a = _paper_with_chunks(db, "A", ["dense retrieval for question answering", "reranking passages"])
    b = _paper_with_chunks(db, "B", ["retrieval augmented generation"])
    i1 = FaissWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path / "one")
    i2 = FaissWorkspaceIndex(db, workspace_id="ws_1", index_dir=tmp_path / "two")
    i1.rebuild([a, b])
    i2.rebuild([a, b])
    assert [h.model_dump() for h in i1.search("retrieval", k=10)] == [
        h.model_dump() for h in i2.search("retrieval", k=10)
    ]


def test_lru_cache_evicts_least_recently_used(db: Session, tmp_path: Path) -> None:
    ws = {name: _paper_with_chunks(db, name, [f"text for {name}"]) for name in ("w1", "w2", "w3")}
    cache = WorkspaceIndexCache(max_size=2)

    for name, pid in ws.items():
        idx = cache.get_or_build(db, workspace_id=name, index_dir=tmp_path, paper_ids=[pid])
        assert idx.paper_ids() == [pid]

    assert cache.resident_ids() == ["w2", "w3"]  # w1 evicted

    # touching w2 makes w3 the LRU; adding w1 back evicts w3
    cache.get_or_build(db, workspace_id="w2", index_dir=tmp_path, paper_ids=[ws["w2"]])
    cache.get_or_build(db, workspace_id="w1", index_dir=tmp_path, paper_ids=[ws["w1"]])
    assert cache.resident_ids() == ["w2", "w1"]


def test_factory_returns_faiss_backend_when_requested(db: Session, tmp_path: Path) -> None:
    idx = get_workspace_index(db, workspace_id="ws_1", index_dir=tmp_path, backend="faiss")
    assert isinstance(idx, FaissWorkspaceIndex)
