"""Multi-paper retrieval (Architecture §3 S13 "Multi-paper RAG retrieve";
Roadmap Phase 9). k≈8 over the workspace combined index, optionally scoped
to a subset of papers. Deterministic given a deterministic index.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repository as repo
from app.domain.rag import RetrievedChunk
from app.retrieval.workspace_index import WorkspaceChunkIndex


def retrieve(
    db: Session,
    index: WorkspaceChunkIndex,
    query: str,
    *,
    k: int,
    scope_paper_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    if k <= 0 or not query.strip():
        return []
    # a scope is searched within: its papers' passages ranked among themselves
    raw = index.search(query, k, paper_ids=scope_paper_ids)[:k]

    meta = {c.chunk_id: c for c in repo.get_chunks_by_ids(db, [h.chunk_id for h in raw])}
    out: list[RetrievedChunk] = []
    for h in raw:
        c = meta.get(h.chunk_id)
        out.append(
            RetrievedChunk(
                chunk_id=h.chunk_id,
                paper_id=h.paper_id,
                text=h.text,
                section=c.section if c else None,
                page=c.page if c else None,
                score=h.score,
            )
        )
    return out
