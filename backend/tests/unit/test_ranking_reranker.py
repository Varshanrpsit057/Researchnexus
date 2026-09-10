from __future__ import annotations

import pytest

from app.retrieval.reranker import (
    FakeCrossEncoder,
    RerankerBackendUnavailable,
    SentenceTransformersCrossEncoder,
    get_reranker,
)


def test_fake_cross_encoder_scores_are_bounded_and_reward_overlap() -> None:
    ce = FakeCrossEncoder()
    query = "retrieval augmented generation for question answering"
    scores = ce.score(query, ["retrieval augmented generation methods", "image classification with cnns", ""])
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[0] > scores[1]  # the on-topic passage scores higher
    assert scores[2] == 0.0  # empty passage


def test_fake_cross_encoder_is_deterministic() -> None:
    ce = FakeCrossEncoder()
    a = ce.score("a b c", ["a b x", "c d e"])
    b = ce.score("a b c", ["a b x", "c d e"])
    assert a == b


def test_fake_cross_encoder_handles_empty_passage_list() -> None:
    assert FakeCrossEncoder().score("anything", []) == []


def test_get_reranker_returns_the_named_backend() -> None:
    assert isinstance(get_reranker("fake"), FakeCrossEncoder)
    with pytest.raises(ValueError):
        get_reranker("nope")


def test_real_cross_encoder_raises_a_clear_error_without_its_dependency() -> None:
    ce = SentenceTransformersCrossEncoder()
    with pytest.raises(RerankerBackendUnavailable):
        ce.score("q", ["p"])
