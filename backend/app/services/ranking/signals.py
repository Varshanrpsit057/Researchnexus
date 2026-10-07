"""The seven ranking sub-scores (Data Model §4 `SignalScores`; Architecture
§3 S9 "one function per sub-score"). Every function is pure and
deterministic -- no LLM, no I/O -- and returns `float | None`, where `None`
means "the input for this signal was missing" so fuse.py can renormalise
the weights over the signals that were actually computed.

Similarity signals map cosine in [-1, 1] to [0, 1] by clamping negatives to
0 ("embeddings pointing apart" == "no similarity"), so every score is a
comparable [0, 1] value.
"""

from __future__ import annotations

import math

import numpy as np

from app.domain.candidate import CitationRelationship

_CITATION_ONE_HOP = 1.0
_CITATION_TWO_HOP = 0.6
_CITATION_CO_CITED = 0.6


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype="float32")
    b = np.asarray(b, dtype="float32")
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 0.0 if denom == 0.0 else float(np.dot(a, b) / denom)


def _sim(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    if a is None or b is None:
        return None
    return round(clamp01(cosine(a, b)), 6)


def semantic_doc_signal(seed_doc: np.ndarray | None, candidate_doc: np.ndarray | None) -> float | None:
    return _sim(seed_doc, candidate_doc)


def semantic_chunk_signal(seed_chunks: np.ndarray | None, candidate_vec: np.ndarray | None) -> float | None:
    if seed_chunks is None or candidate_vec is None or len(seed_chunks) == 0:
        return None
    return round(clamp01(max(cosine(chunk, candidate_vec) for chunk in seed_chunks)), 6)


def problem_sim_signal(problem_vec: np.ndarray | None, candidate_vec: np.ndarray | None) -> float | None:
    return _sim(problem_vec, candidate_vec)


def method_sim_signal(method_vec: np.ndarray | None, candidate_vec: np.ndarray | None) -> float | None:
    return _sim(method_vec, candidate_vec)


def dataset_overlap_signal(profile_datasets: list[str], candidate_text: str) -> float | None:
    names = [d.strip().lower() for d in profile_datasets if d.strip()]
    if not names:
        return None
    text = candidate_text.lower()
    hits = sum(1 for name in names if name in text)
    return round(clamp01(hits / len(names)), 6)


def citation_signal(relationship: CitationRelationship, hops: int | None) -> float | None:
    if relationship in (CitationRelationship.CITED_BY_SEED, CitationRelationship.CITES_SEED):
        return _CITATION_ONE_HOP if (hops or 1) <= 1 else _CITATION_TWO_HOP
    if relationship is CitationRelationship.CO_CITED:
        return _CITATION_CO_CITED
    return None  # NONE: discovery found no link -> not a penalty, just renormalise


def publisher_signal(publisher: str | None, preferred: tuple[str, ...] | None = None) -> float:
    """1.0 for a paper from a publisher the reader prefers (`preferred`, as
    `publishers.preferred_set` names them; None is the default four), else
    0.0 -- an unknown publisher counts as not preferred, never as missing, so
    the criterion means the same for every paper."""
    from app.services.metadata.publishers import normalize, preferred_set

    chosen = preferred if preferred is not None else preferred_set(None)
    return 1.0 if normalize(publisher) in chosen else 0.0


def recency_signal(year: int | None, current_year: int, *, half_life_years: float) -> float | None:
    if year is None:
        return None
    age = max(0, current_year - year)
    return round(clamp01(math.exp(-age / half_life_years)), 6)
