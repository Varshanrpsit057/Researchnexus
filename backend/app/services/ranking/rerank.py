"""Cross-encoder rerank of the top slice (Architecture §3 S9 `rerank.py`;
Data Model §4: "applied to the top `RERANK_TOP_N` (default 50)").

Pure and deterministic given a deterministic reranker: takes the candidates
already ordered by `fused_score` and returns `{candidate_id: rerank_score}`
for the top `top_n` only. The pipeline decides how the rerank score changes
the final ordering.
"""

from __future__ import annotations

from app.retrieval.reranker import CrossEncoderReranker


def rerank_scores(
    query: str,
    ordered_passages: list[tuple[str, str]],
    reranker: CrossEncoderReranker,
    top_n: int,
) -> dict[str, float]:
    head = ordered_passages[: max(0, top_n)]
    if not head:
        return {}
    scores = reranker.score(query, [passage for _cid, passage in head])
    return {cid: round(float(score), 6) for (cid, _passage), score in zip(head, scores, strict=True)}
