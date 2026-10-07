"""The six ranking criteria a researcher sets (remediation Phase 9): how they
become the real fusion weights, how they are validated and stamped, and an
explanation that says what each signal actually added to a paper's score."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.ranking import CRITERIA, RankingCriteria, RankingWeights, SignalScores
from app.services.ranking.explain import build_explanation
from app.services.ranking.fuse import fuse


def test_the_default_criteria_are_the_initial_weights_plus_a_preferred_publisher() -> None:
    # the reader chose (2026-10-02) to have IEEE, Springer, ACM and Elsevier papers count, at 15
    defaults = RankingCriteria()
    assert defaults.publisher == 15
    assert defaults.to_weights().version == "c-42.18.14.8.12.6.15"
    assert defaults.to_weights().publisher == pytest.approx(15 / 115)
    # the initial weights are the same criteria without that preference, and keep their version
    initial = RankingCriteria(publisher=0)
    assert initial.to_weights() == RankingWeights()
    assert RankingCriteria.from_weights_version("w0-initial") == initial


def test_custom_criteria_become_weights_in_proportion_with_a_stamped_version() -> None:
    criteria = RankingCriteria(topic=60, problem=20, methods=10, datasets=0, citations=10, recency=0, publisher=0)
    w = criteria.to_weights()
    assert w.version == "c-60.20.10.0.10.0.0"
    # topic counts document and passage similarity, 2:1, as the initial weights do
    assert w.semantic_doc == pytest.approx(0.4) and w.semantic_chunk == pytest.approx(0.2)
    assert (w.problem_sim, w.method_sim, w.dataset_overlap, w.citation, w.recency) == pytest.approx((0.2, 0.1, 0.0, 0.1, 0.0))
    assert sum(w.as_dict().values()) == pytest.approx(1.0)
    # the version carries the criteria, so a saved ranking says what it was ranked by
    assert RankingCriteria.from_weights_version(w.version) == criteria


def test_only_proportions_matter() -> None:
    assert RankingCriteria(topic=2, problem=1, methods=0, datasets=0, citations=0, recency=0, publisher=1).to_weights().as_dict() == pytest.approx(
        RankingCriteria(topic=40, problem=20, methods=0, datasets=0, citations=0, recency=0, publisher=20).to_weights().as_dict()
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"topic": -1},
        {"recency": 101},
        {"topic": 0, "problem": 0, "methods": 0, "datasets": 0, "citations": 0, "recency": 0, "publisher": 0},
        {"novelty": 10},
    ],
)
def test_criteria_out_of_range_all_zero_or_unknown_are_refused(bad: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        RankingCriteria(**bad)


def test_an_unknown_weights_version_reads_as_no_criteria() -> None:
    assert RankingCriteria.from_weights_version("w9-someday") is None
    assert RankingCriteria.from_weights_version("c-1.2") is None
    assert CRITERIA == ("topic", "problem", "methods", "datasets", "citations", "recency", "publisher")
    # a ranking saved before the publisher criterion existed reads as giving it nothing
    assert RankingCriteria.from_weights_version("c-60.20.10.0.10.0") == RankingCriteria(
        topic=60, problem=20, methods=10, datasets=0, citations=10, recency=0, publisher=0
    )


def test_the_explanation_gives_each_signals_value_weight_and_contribution() -> None:
    weights = RankingCriteria(topic=50, problem=50, methods=0, datasets=0, citations=0, recency=0, publisher=0).to_weights()
    signals = SignalScores(semantic_doc=0.9, semantic_chunk=None, problem_sim=0.5, citation=1.0)
    fusion = fuse(signals, weights)
    explanation = build_explanation(signals, threshold=0.5, fusion=fusion)

    by_signal = {c.signal: c for c in explanation.contributions}
    # passage similarity wasn't computed: its weight went to the computed signals (signals
    # these criteria give nothing aren't "missing" -- they don't count either way)
    assert explanation.missing_signals == ["semantic_chunk"]
    assert set(by_signal) == {"semantic_doc", "problem_sim", "citation"}
    assert sum(c.weight for c in explanation.contributions) == pytest.approx(1.0)
    for c in explanation.contributions:
        assert c.contribution == pytest.approx(c.value * c.weight)
    assert sum(c.contribution for c in explanation.contributions) == pytest.approx(fusion.fused_score)
    # a computed signal with no weight is shown, contributing nothing
    assert by_signal["citation"].weight == 0 and by_signal["citation"].contribution == 0
    # strongest contribution first
    assert [c.signal for c in explanation.contributions][0] == "semantic_doc"
