"""Cross-encoder rerank of retrieved chunks (Architecture §3 S13
"retrieve -> rerank ... top ~5"; Roadmap Phase 9).

A cross-encoder is a retrieval model, not an LLM. Without one ("none", the
default) the retriever's order stands; `SentenceTransformersCrossEncoder` is
opt-in via `settings.rag_reranker`; `FakeCrossEncoder` (token-Jaccard) is
what tests use.
"""

from __future__ import annotations

from app.domain.rag import RetrievedChunk
from app.retrieval.reranker import CrossEncoderReranker


def rerank(
    query: str,
    chunks: list[RetrievedChunk],
    reranker: CrossEncoderReranker,
    top_n: int,
) -> list[RetrievedChunk]:
    if not chunks:
        return []
    if reranker.name == "none":
        return list(chunks[: max(0, top_n)])  # no cross-encoder: the retrieval order stands
    scores = reranker.score(query, [c.text for c in chunks])
    scored = [
        c.model_copy(update={"rerank_score": round(float(s), 6)})
        for c, s in zip(chunks, scores, strict=True)
    ]
    scored.sort(key=lambda c: (-(c.rerank_score or 0.0), c.chunk_id))
    return scored[: max(0, top_n)]
