from __future__ import annotations

from app.domain.profile import Confidence
from app.domain.ranking import (
    SIGNAL_NAMES,
    RankedPaper,
    RankingExplanation,
    RankingWeights,
    SignalScores,
)


def test_w0_initial_weights_sum_to_one() -> None:
    weights = RankingWeights()
    assert weights.version == "w0-initial"
    total = sum(weights.as_dict().values())
    assert abs(total - 1.0) < 1e-9
    assert set(weights.as_dict()) == set(SIGNAL_NAMES)


def test_signal_scores_available_drops_none() -> None:
    scores = SignalScores(semantic_doc=0.8, problem_sim=0.0, recency=None)
    available = scores.available()
    assert available == {"semantic_doc": 0.8, "problem_sim": 0.0}
    assert "recency" not in available


def test_signal_scores_all_none_is_empty() -> None:
    assert SignalScores().available() == {}


def test_ranking_explanation_defaults() -> None:
    expl = RankingExplanation(bullet_reasons=["x"], prose="x.")
    assert expl.signals_used == []
    assert expl.template_only is False


def test_ranked_paper_round_trips_through_json() -> None:
    rp = RankedPaper(
        candidate_id="cand_1",
        signals=SignalScores(semantic_doc=0.7),
        weights_version="w0-initial",
        fused_score=0.7,
        rerank_score=None,
        final_rank=1,
        band=Confidence.HIGH,
        explanation=RankingExplanation(bullet_reasons=["a"], prose="a.", signals_used=["semantic_doc"]),
    )
    restored = RankedPaper.model_validate(rp.model_dump())
    assert restored == rp
