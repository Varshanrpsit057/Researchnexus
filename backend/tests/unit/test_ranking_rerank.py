from __future__ import annotations

from app.retrieval.reranker import FakeCrossEncoder
from app.services.ranking.rerank import rerank_scores


def test_rerank_scores_only_the_top_n_slice() -> None:
    passages = [(f"cand_{i}", f"passage number {i}") for i in range(10)]
    scores = rerank_scores("query about passage number 3", passages, FakeCrossEncoder(), top_n=4)
    assert set(scores) == {"cand_0", "cand_1", "cand_2", "cand_3"}
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_rerank_scores_is_deterministic() -> None:
    passages = [("a", "alpha beta"), ("b", "gamma delta")]
    ce = FakeCrossEncoder()
    assert rerank_scores("alpha", passages, ce, top_n=5) == rerank_scores("alpha", passages, ce, top_n=5)


def test_rerank_scores_empty_input() -> None:
    assert rerank_scores("q", [], FakeCrossEncoder(), top_n=50) == {}


def test_rerank_scores_top_n_larger_than_list_scores_everything() -> None:
    passages = [("a", "x"), ("b", "y")]
    scores = rerank_scores("x", passages, FakeCrossEncoder(), top_n=50)
    assert set(scores) == {"a", "b"}
