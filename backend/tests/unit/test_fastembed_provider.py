"""FastEmbedEmbeddingProvider with the model stubbed out (no download):
L2-normalised output, rows aligned with the input, and the text cache."""

from __future__ import annotations

import numpy as np

from app.retrieval.embeddings import FastEmbedEmbeddingProvider, discovery_embedder


class _StubModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]):
        self.calls.append(list(texts))
        for t in texts:
            yield np.array([len(t), 1.0, 0.0], dtype="float32")


def _provider() -> tuple[FastEmbedEmbeddingProvider, _StubModel]:
    provider = FastEmbedEmbeddingProvider()
    model = _StubModel()
    provider._model = model  # skip the real (downloaded) model
    return provider, model


def test_vectors_are_unit_length_and_aligned_with_input() -> None:
    provider, _ = _provider()
    out = provider.embed(["ab", "abcd", "ab"])
    assert out.shape == (3, 3)
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, rtol=1e-6)
    np.testing.assert_array_equal(out[0], out[2])
    assert not np.allclose(out[0], out[1])


def test_texts_already_embedded_are_not_embedded_again() -> None:
    provider, model = _provider()
    provider.embed(["seed", "candidate one"])
    provider.embed(["candidate one", "candidate two"])
    assert model.calls == [["seed", "candidate one"], ["candidate two"]]


def test_no_embedder_when_disabled() -> None:
    from pathlib import Path

    assert discovery_embedder("none", model_dir=Path(".")) is None
