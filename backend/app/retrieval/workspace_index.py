"""Workspace-level combined chunk index (Roadmap Phase 8 seam + Phase 9
FAISS implementation; Architecture §3 S13 "combined chunk index", §7
"FAISS IndexFlatIP ... on disk, LRU-cached").

Two implementations of the `WorkspaceChunkIndex` Protocol:

- `DbBackedWorkspaceIndex` (Phase 8) -- deterministic, dependency-free;
  resolves the workspace's chunks from `paper_chunks` and scores `search`
  with lexical token overlap. Kept as the default so the Phase 8 workspace
  pipeline stays dependency-light.
- `FaissWorkspaceIndex` (Phase 9) -- real vector retrieval. Embeds every
  member chunk once (MiniLM in prod, `FakeEmbeddingProvider` -- a
  deterministic hash embedder -- by default so tests are hermetic and
  reproducible), stores the vectors in an `IndexFlatIP` (the pure-numpy
  reference impl by default, `faiss.IndexFlatIP` when `vector_backend=
  "faiss"`), and persists `<ws>.npz` (vectors) + `<ws>.meta.json` so
  `load()` never re-embeds. `WorkspaceIndexCache` is the LRU that keeps a
  bounded number of these resident.

The manifest (member paper ids + chunk count + on-disk path) is what
`workspaces.combined_index_path` points at.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import PaperChunkORM
from app.domain.chunk import ChunkKind
from app.retrieval.embeddings import EmbeddingProvider, FakeEmbeddingProvider, discovery_embedder
from app.retrieval.faiss_store import get_vector_index

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe(paper_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for pid in paper_ids:
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


class WorkspaceIndexHit(BaseModel):
    chunk_id: str
    paper_id: str
    score: float
    text: str


class WorkspaceIndexManifest(BaseModel):
    workspace_id: str
    paper_ids: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    index_path: str | None = None
    built_at: datetime = Field(default_factory=_utcnow)


class WorkspaceChunkIndex(Protocol):
    """The stable contract Phase 9 RAG builds on. Every membership-changing
    call returns the fresh manifest so the caller can persist
    `combined_index_path`."""

    def rebuild(self, paper_ids: list[str]) -> WorkspaceIndexManifest: ...
    def add_paper(self, paper_id: str) -> WorkspaceIndexManifest: ...
    def remove_paper(self, paper_id: str) -> WorkspaceIndexManifest: ...
    def paper_ids(self) -> list[str]: ...
    def search(self, query: str, k: int, paper_ids: Collection[str] | None = None) -> list[WorkspaceIndexHit]: ...
    def manifest(self) -> WorkspaceIndexManifest: ...


def _manifest_path(index_dir: Path, workspace_id: str) -> Path:
    return index_dir / f"{workspace_id}.json"


def load_manifest(index_dir: Path, workspace_id: str) -> WorkspaceIndexManifest | None:
    path = _manifest_path(index_dir, workspace_id)
    if not path.exists():
        return None
    return WorkspaceIndexManifest.model_validate_json(path.read_text(encoding="utf-8"))


def prefer_full_text(rows: list[PaperChunkORM]) -> list[PaperChunkORM]:
    """A paper read in full is searched in full (remediation Phase 11): once
    it has full-text chunks, its separate abstract chunk -- kept in the
    database for the answers that already cite it -- is left out of search,
    so the abstract never stands in for the paper's own text. A paper with
    only its abstract is still searched by its abstract."""
    abstract = ChunkKind.ABSTRACT.value
    read_in_full = {r.paper_id for r in rows if r.kind != abstract}
    return [r for r in rows if r.kind != abstract or r.paper_id not in read_in_full]


class _IndexedChunk(BaseModel):
    chunk_id: str
    paper_id: str
    text: str
    tokens: set[str]


class DbBackedWorkspaceIndex:
    """Deterministic, dependency-free `WorkspaceChunkIndex` (Phase 8).

    Membership is an ordered list of paper ids; the searchable content is
    every `paper_chunks` row for those papers. Lexical Jaccard scoring, no
    embeddings, no FAISS.
    """

    def __init__(self, db: Session, *, workspace_id: str, index_dir: Path) -> None:
        self._db = db
        self._workspace_id = workspace_id
        self._index_dir = Path(index_dir)
        self._paper_ids: list[str] = []
        self._chunks: list[_IndexedChunk] = []

    def rebuild(self, paper_ids: list[str]) -> WorkspaceIndexManifest:
        self._paper_ids = _dedupe(paper_ids)
        self._reload_chunks()
        return self._persist_manifest()

    def add_paper(self, paper_id: str) -> WorkspaceIndexManifest:
        if paper_id not in self._paper_ids:
            self._paper_ids.append(paper_id)
            self._reload_chunks()
        return self._persist_manifest()

    def remove_paper(self, paper_id: str) -> WorkspaceIndexManifest:
        if paper_id in self._paper_ids:
            self._paper_ids.remove(paper_id)
            self._reload_chunks()
        return self._persist_manifest()

    def paper_ids(self) -> list[str]:
        return list(self._paper_ids)

    def search(self, query: str, k: int, paper_ids: Collection[str] | None = None) -> list[WorkspaceIndexHit]:
        q = _tokens(query)
        if not q or k <= 0:
            return []
        allow = set(paper_ids) if paper_ids is not None else None
        scored: list[WorkspaceIndexHit] = []
        for chunk in self._chunks:
            if allow is not None and chunk.paper_id not in allow:
                continue
            overlap = len(q & chunk.tokens)
            if overlap == 0:
                continue
            score = overlap / len(q | chunk.tokens)
            scored.append(
                WorkspaceIndexHit(chunk_id=chunk.chunk_id, paper_id=chunk.paper_id, score=score, text=chunk.text)
            )
        scored.sort(key=lambda h: (-h.score, h.chunk_id))
        return scored[:k]

    def manifest(self) -> WorkspaceIndexManifest:
        return WorkspaceIndexManifest(
            workspace_id=self._workspace_id,
            paper_ids=list(self._paper_ids),
            chunk_count=len(self._chunks),
            index_path=str(_manifest_path(self._index_dir, self._workspace_id)),
        )

    def _reload_chunks(self) -> None:
        if not self._paper_ids:
            self._chunks = []
            return
        rows = (
            self._db.execute(
                select(PaperChunkORM).where(PaperChunkORM.paper_id.in_(self._paper_ids)).order_by(PaperChunkORM.id)
            )
            .scalars()
            .all()
        )
        self._chunks = [
            _IndexedChunk(chunk_id=r.id, paper_id=r.paper_id, text=r.text, tokens=_tokens(r.text))
            for r in prefer_full_text(list(rows))
        ]

    def _persist_manifest(self) -> WorkspaceIndexManifest:
        self._index_dir.mkdir(parents=True, exist_ok=True)
        manifest = self.manifest()
        _manifest_path(self._index_dir, self._workspace_id).write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        return manifest


class FaissWorkspaceIndex:
    """Vector `WorkspaceChunkIndex` (Phase 9). `IndexFlatIP` over
    L2-normalised chunk embeddings -> inner product == cosine similarity."""

    def __init__(
        self,
        db: Session,
        *,
        workspace_id: str,
        index_dir: Path,
        embedder: EmbeddingProvider | None = None,
        vector_backend: str = "numpy",
    ) -> None:
        self._db = db
        self._workspace_id = workspace_id
        self._index_dir = Path(index_dir)
        self._embedder: EmbeddingProvider = embedder or FakeEmbeddingProvider()
        self._vector_backend = vector_backend
        self._paper_ids: list[str] = []
        self._meta: list[dict[str, str]] = []  # row-aligned: {chunk_id, paper_id, text}
        self._vectors = np.zeros((0, self._embedder.dimension), dtype="float32")

    # -- membership ----------------------------------------------------
    def rebuild(self, paper_ids: list[str]) -> WorkspaceIndexManifest:
        self._paper_ids = _dedupe(paper_ids)
        rows: list[PaperChunkORM] = []
        if self._paper_ids:
            rows = list(
                self._db.execute(
                    select(PaperChunkORM)
                    .where(PaperChunkORM.paper_id.in_(self._paper_ids))
                    .order_by(PaperChunkORM.id)
                )
                .scalars()
                .all()
            )
        rows = prefer_full_text(rows)
        self._meta = [{"chunk_id": r.id, "paper_id": r.paper_id, "text": r.text} for r in rows]
        if rows:
            self._vectors = _l2norm(self._embedder.embed([r.text for r in rows]))
        else:
            self._vectors = np.zeros((0, self._embedder.dimension), dtype="float32")
        return self._persist()

    def add_paper(self, paper_id: str) -> WorkspaceIndexManifest:
        if paper_id in self._paper_ids:
            return self.manifest()
        return self.rebuild([*self._paper_ids, paper_id])

    def remove_paper(self, paper_id: str) -> WorkspaceIndexManifest:
        if paper_id not in self._paper_ids:
            return self.manifest()
        return self.rebuild([p for p in self._paper_ids if p != paper_id])

    # -- reads -------------------------------------------------------
    def paper_ids(self) -> list[str]:
        return list(self._paper_ids)

    def search(self, query: str, k: int, paper_ids: Collection[str] | None = None) -> list[WorkspaceIndexHit]:
        if k <= 0 or not query.strip() or self._vectors.shape[0] == 0:
            return []
        if paper_ids is not None:
            # ranked among these papers' passages only: a search limited to one
            # paper must find that paper's best passages, however the rest of
            # the workspace would have ranked (remediation, 2026-10-02 -- taking
            # the workspace's top hits and filtering them left a short paper in
            # a large workspace with nothing, and its comparison said "no text")
            allow = set(paper_ids)
            rows = [i for i, m in enumerate(self._meta) if m["paper_id"] in allow]
            if not rows:
                return []
            qv = _l2norm(self._embedder.embed([query]))[0]
            scores = self._vectors[rows] @ qv
            scoped = [
                WorkspaceIndexHit(
                    chunk_id=self._meta[i]["chunk_id"],
                    paper_id=self._meta[i]["paper_id"],
                    score=round(float(score), 6),
                    text=self._meta[i]["text"],
                )
                for i, score in zip(rows, scores, strict=True)
            ]
            scoped.sort(key=lambda h: (-h.score, h.chunk_id))
            return scoped[:k]
        index = get_vector_index(self._vector_backend, self._embedder.dimension)
        index.add([m["chunk_id"] for m in self._meta], self._vectors)
        qv = _l2norm(self._embedder.embed([query]))[0]
        by_id = {m["chunk_id"]: m for m in self._meta}
        hits = [
            WorkspaceIndexHit(
                chunk_id=cid, paper_id=by_id[cid]["paper_id"], score=round(float(score), 6), text=by_id[cid]["text"]
            )
            for cid, score in index.search(qv, k * 4)
            if cid in by_id
        ]
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:k]

    def manifest(self) -> WorkspaceIndexManifest:
        return WorkspaceIndexManifest(
            workspace_id=self._workspace_id,
            paper_ids=list(self._paper_ids),
            chunk_count=len(self._meta),
            index_path=str(_manifest_path(self._index_dir, self._workspace_id)),
        )

    # -- persistence -----------------------------------------------
    def _persist(self) -> WorkspaceIndexManifest:
        self._index_dir.mkdir(parents=True, exist_ok=True)
        np.savez(
            self._index_dir / f"{self._workspace_id}.npz",
            vectors=self._vectors,
            chunk_ids=np.array([m["chunk_id"] for m in self._meta], dtype="<U128"),
            dimension=np.array([self._embedder.dimension]),
        )
        (self._index_dir / f"{self._workspace_id}.meta.json").write_text(
            json.dumps({"paper_ids": self._paper_ids, "chunks": self._meta}, indent=2), encoding="utf-8"
        )
        manifest = self.manifest()
        _manifest_path(self._index_dir, self._workspace_id).write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        return manifest

    @classmethod
    def load(
        cls,
        db: Session,
        *,
        workspace_id: str,
        index_dir: Path,
        embedder: EmbeddingProvider | None = None,
        vector_backend: str = "numpy",
    ) -> FaissWorkspaceIndex | None:
        index_dir = Path(index_dir)
        meta_path = index_dir / f"{workspace_id}.meta.json"
        npz_path = index_dir / f"{workspace_id}.npz"
        if not meta_path.exists() or not npz_path.exists():
            return None
        idx = cls(
            db,
            workspace_id=workspace_id,
            index_dir=index_dir,
            embedder=embedder,
            vector_backend=vector_backend,
        )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        idx._paper_ids = list(meta.get("paper_ids", []))
        idx._meta = list(meta.get("chunks", []))
        data = np.load(npz_path)  # allow_pickle defaults False; dtypes are numeric/unicode
        idx._vectors = data["vectors"].astype("float32")
        return idx


def _l2norm(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype="float32")
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0.0, 1.0, norms)


class WorkspaceIndexCache:
    """Bounded LRU of resident `FaissWorkspaceIndex` instances (Architecture
    §7: "LRU-cached" combined indices). `get_or_build` loads from disk when
    a matching persisted index exists, otherwise rebuilds from the DB."""

    def __init__(
        self,
        *,
        max_size: int = 8,
        embedder: EmbeddingProvider | None = None,
        vector_backend: str = "numpy",
    ) -> None:
        self._max = max(1, max_size)
        self._embedder = embedder
        self._vector_backend = vector_backend
        self._store: OrderedDict[str, FaissWorkspaceIndex] = OrderedDict()

    def get_or_build(
        self, db: Session, *, workspace_id: str, index_dir: Path, paper_ids: list[str]
    ) -> FaissWorkspaceIndex:
        want = _dedupe(paper_ids)
        if workspace_id in self._store:
            idx = self._store[workspace_id]
            if idx.paper_ids() != want:
                idx.rebuild(want)
            self._store.move_to_end(workspace_id)
            return idx

        loaded = FaissWorkspaceIndex.load(
            db,
            workspace_id=workspace_id,
            index_dir=index_dir,
            embedder=self._embedder,
            vector_backend=self._vector_backend,
        )
        if loaded is not None and loaded.paper_ids() == want:
            idx = loaded
        else:
            idx = FaissWorkspaceIndex(
                db,
                workspace_id=workspace_id,
                index_dir=index_dir,
                embedder=self._embedder,
                vector_backend=self._vector_backend,
            )
            idx.rebuild(want)
        self._store[workspace_id] = idx
        self._store.move_to_end(workspace_id)
        while len(self._store) > self._max:
            self._store.popitem(last=False)
        return idx

    def invalidate(self, workspace_id: str) -> None:
        self._store.pop(workspace_id, None)

    def resident_ids(self) -> list[str]:
        return list(self._store.keys())


def workspace_search_index(db: Session, *, workspace_id: str, settings: Settings) -> WorkspaceChunkIndex:
    """The index chat and comparison search a workspace with: semantic, on
    the process's shared real embedder (`settings.rag_embedder`, loaded
    once); the lexical index when that embedder can't load (e.g. offline
    before the model's first download) -- never the hash stand-in."""
    index_dir = Path(settings.data_dir) / "workspace_index"
    embedder = discovery_embedder(settings.rag_embedder, model_dir=settings.model_cache_dir(), threads=settings.embedding_threads)
    if embedder is None:
        return DbBackedWorkspaceIndex(db, workspace_id=workspace_id, index_dir=index_dir)
    return FaissWorkspaceIndex(
        db, workspace_id=workspace_id, index_dir=index_dir, embedder=embedder, vector_backend=settings.rag_vector_backend
    )


def get_workspace_index(
    db: Session, *, workspace_id: str, index_dir: Path, backend: str = "db"
) -> WorkspaceChunkIndex:
    """Factory. `backend="db"` -> the Phase 8 lexical stand-in (default,
    what the workspace pipeline uses); `backend="faiss"` -> the Phase 9
    vector index."""
    if backend == "faiss":
        return FaissWorkspaceIndex(db, workspace_id=workspace_id, index_dir=Path(index_dir))
    return DbBackedWorkspaceIndex(db, workspace_id=workspace_id, index_dir=Path(index_dir))
