"""Cross-encoder reranker interfaces (retrieval layer). Mirrors the
lazy-optional pattern of app/retrieval/embeddings.py:

- `FakeCrossEncoder` is deterministic and dependency-free (token-Jaccard
  of query vs passage) -- the default, and what tests use;
- `SentenceTransformersCrossEncoder` lazy-imports `sentence-transformers`
  (the optional `embeddings` extra) and raises `RerankerBackendUnavailable`
  if it is not installed.

A cross-encoder is a retrieval model, not an LLM (Architecture §3 S9).
"""

from __future__ import annotations

import math
import re
from typing import Protocol

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class CrossEncoderReranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class RerankerBackendUnavailable(RuntimeError):
    """Raised when the real cross-encoder's dependency is not installed."""


class FakeCrossEncoder:
    """Deterministic stand-in: score = |q ∩ p| / |q ∪ p| in [0, 1]. Not a
    real relevance model -- used for offline tests and as the default until
    `sentence-transformers` is installed."""

    name = "fake"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = _tokens(query)
        out: list[float] = []
        for passage in passages:
            p = _tokens(passage)
            union = q | p
            out.append(round(len(q & p) / len(union), 6) if union else 0.0)
        return out


class SentenceTransformersCrossEncoder:
    """`cross-encoder/ms-marco-MiniLM-L-6-v2`, lazy-loaded. Outputs are
    logits, squashed to [0, 1] with a sigmoid so they compose with the
    fused score. Requires the optional `embeddings` extra."""

    name = "cross-encoder"
    _MODEL_ID = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self) -> None:
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise RerankerBackendUnavailable(
                    "sentence-transformers is not installed; install the 'embeddings' extra "
                    "(pip install -e '.[embeddings]')"
                ) from e
            self._model = CrossEncoder(self._MODEL_ID)
        return self._model

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        model = self._load()
        raw = model.predict([(query, p) for p in passages])  # type: ignore[attr-defined]
        return [round(1.0 / (1.0 + math.exp(-float(x))), 6) for x in raw]


_BACKENDS: dict[str, type] = {"fake": FakeCrossEncoder, "cross-encoder": SentenceTransformersCrossEncoder}


def get_reranker(name: str) -> CrossEncoderReranker:
    try:
        backend_cls = _BACKENDS[name]
    except KeyError as e:
        raise ValueError(f"unknown reranker backend: {name!r} (known: {sorted(_BACKENDS)})") from e
    return backend_cls()
