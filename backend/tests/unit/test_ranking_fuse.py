from __future__ import annotations

from app.domain.ranking import RankingWeights, SignalScores
from app.services.ranking.fuse import fuse


def test_full_signals_fuse_to_the_plain_weighted_sum() -> None:
    weights = RankingWeights()  # sums to 1.0, so no renormalisation
    signals = SignalScores(
        semantic_doc=1.0,
        semantic_chunk=1.0,
        problem_sim=1.0,
        method_sim=1.0,
        dataset_overlap=1.0,
        citation=1.0,
        recency=1.0,
    )
    result = fuse(signals, weights)
    assert abs(result.fused_score - 1.0) < 1e-9
    assert result.missing_signals == []
    assert abs(sum(result.effective_weights.values()) - 1.0) < 1e-9


def test_missing_signals_renormalise_the_weights_over_what_is_available() -> None:
    weights = RankingWeights()
    signals = SignalScores(semantic_doc=0.5, problem_sim=1.0)  # only two available
    result = fuse(signals, weights)

    w_doc, w_prob = weights.semantic_doc, weights.problem_sim
    total = w_doc + w_prob
    expected = (w_doc / total) * 0.5 + (w_prob / total) * 1.0
    assert abs(result.fused_score - expected) < 1e-9
    assert abs(sum(result.effective_weights.values()) - 1.0) < 1e-9
    assert set(result.missing_signals) == {"semantic_chunk", "method_sim", "dataset_overlap", "citation", "recency"}
    assert set(result.used_signals) == {"semantic_doc", "problem_sim"}


def test_no_signals_available_gives_zero() -> None:
    result = fuse(SignalScores(), RankingWeights())
    assert result.fused_score == 0.0
    assert result.used_signals == []
    assert result.effective_weights == {}


def test_raising_one_signal_never_lowers_the_fused_score() -> None:
    weights = RankingWeights()
    base = SignalScores(semantic_doc=0.4, problem_sim=0.4, citation=0.4)
    lower = fuse(base, weights).fused_score
    for bump in (0.5, 0.7, 1.0):
        raised = fuse(SignalScores(semantic_doc=bump, problem_sim=0.4, citation=0.4), weights).fused_score
        assert raised >= lower
        lower = raised


def test_fusion_is_deterministic() -> None:
    weights = RankingWeights()
    signals = SignalScores(semantic_doc=0.31, method_sim=0.62, recency=0.9)
    a = fuse(signals, weights)
    b = fuse(signals, weights)
    assert a == b
