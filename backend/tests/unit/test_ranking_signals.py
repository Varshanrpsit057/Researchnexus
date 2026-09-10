from __future__ import annotations

import math

import numpy as np

from app.domain.candidate import CitationRelationship
from app.services.ranking.signals import (
    citation_signal,
    clamp01,
    cosine,
    dataset_overlap_signal,
    method_sim_signal,
    problem_sim_signal,
    recency_signal,
    semantic_chunk_signal,
    semantic_doc_signal,
)


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.asarray(vec, dtype="float32")
    return arr / np.linalg.norm(arr)


def test_clamp01() -> None:
    assert clamp01(-0.3) == 0.0
    assert clamp01(1.7) == 1.0
    assert clamp01(0.42) == 0.42


def test_cosine_of_identical_unit_vectors_is_one() -> None:
    v = _unit([1.0, 2.0, 3.0])
    assert abs(cosine(v, v) - 1.0) < 1e-6


def test_cosine_of_opposite_vectors_is_negative_one() -> None:
    v = _unit([1.0, 0.0, 0.0])
    assert abs(cosine(v, -v) + 1.0) < 1e-6


def test_semantic_doc_signal_clamps_negative_cosine_to_zero() -> None:
    a = _unit([1.0, 0.0])
    b = _unit([-1.0, 0.0])
    assert semantic_doc_signal(a, b) == 0.0
    mixed = semantic_doc_signal(a, _unit([1.0, 1.0]))
    assert mixed is not None and 0.0 <= mixed <= 1.0


def test_semantic_doc_signal_none_when_a_vector_is_missing() -> None:
    assert semantic_doc_signal(None, _unit([1.0, 0.0])) is None
    assert semantic_doc_signal(_unit([1.0, 0.0]), None) is None


def test_semantic_chunk_signal_takes_the_max_over_seed_chunks() -> None:
    seed_chunks = np.stack([_unit([1.0, 0.0]), _unit([0.0, 1.0])])
    cand = _unit([0.9, 0.1])  # closest to the first chunk
    score = semantic_chunk_signal(seed_chunks, cand)
    assert score is not None and score > 0.8
    assert semantic_chunk_signal(None, cand) is None


def test_problem_and_method_sim_are_bounded_and_none_safe() -> None:
    v = _unit([1.0, 1.0, 1.0])
    same = problem_sim_signal(v, v)
    assert same is not None and 0.0 <= same <= 1.0
    assert method_sim_signal(None, v) is None
    assert problem_sim_signal(v, None) is None


def test_dataset_overlap_counts_named_datasets_in_candidate_text() -> None:
    text = "We evaluate on Natural Questions and TriviaQA."
    assert dataset_overlap_signal(["Natural Questions", "TriviaQA"], text) == 1.0
    assert dataset_overlap_signal(["Natural Questions", "SQuAD"], text) == 0.5
    assert dataset_overlap_signal([], text) is None  # profile named no datasets


def test_citation_signal_maps_relationship_to_a_capped_score() -> None:
    assert citation_signal(CitationRelationship.CITED_BY_SEED, 1) == 1.0
    assert citation_signal(CitationRelationship.CITES_SEED, None) == 1.0
    assert citation_signal(CitationRelationship.CITED_BY_SEED, 2) == 0.6  # 2-hop capped
    assert citation_signal(CitationRelationship.CO_CITED, None) == 0.6
    assert citation_signal(CitationRelationship.NONE, None) is None  # no link -> renormalise, don't penalise


def test_recency_signal_is_exponential_decay() -> None:
    assert recency_signal(2026, 2026, half_life_years=4.0) == 1.0
    four_years_old = recency_signal(2022, 2026, half_life_years=4.0)
    assert four_years_old is not None
    assert abs(four_years_old - math.exp(-1.0)) < 1e-6
    assert recency_signal(None, 2026, half_life_years=4.0) is None
    # a future/implausible year still yields a value in [0, 1]
    future = recency_signal(2100, 2026, half_life_years=4.0)
    assert future is not None and 0.0 <= future <= 1.0
