from __future__ import annotations

import numpy as np
import pytest

from app.retrieval.embeddings import (
    EmbeddingBackendUnavailable,
    FakeEmbeddingProvider,
    MiniLMEmbeddingProvider,
    Specter2EmbeddingProvider,
    get_embedding_provider,
)


def test_fake_provider_is_deterministic() -> None:
    provider = FakeEmbeddingProvider()
    v1 = provider.embed(["retrieval augmented generation"])
    v2 = provider.embed(["retrieval augmented generation"])
    np.testing.assert_array_equal(v1, v2)


def test_fake_provider_distinguishes_different_texts() -> None:
    provider = FakeEmbeddingProvider()
    vectors = provider.embed(["paper about retrieval", "paper about summarization"])
    assert vectors.shape == (2, provider.dimension)
    assert not np.array_equal(vectors[0], vectors[1])


def test_fake_provider_vectors_are_unit_norm() -> None:
    provider = FakeEmbeddingProvider()
    vectors = provider.embed(["some text", "another text"])
    norms = np.linalg.norm(vectors, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-5)


def test_get_embedding_provider_factory() -> None:
    provider = get_embedding_provider("fake")
    assert isinstance(provider, FakeEmbeddingProvider)


def test_get_embedding_provider_unknown_name_raises() -> None:
    with pytest.raises(ValueError):
        get_embedding_provider("not-a-real-provider")


def test_minilm_provider_raises_clear_error_without_dependency() -> None:
    provider = MiniLMEmbeddingProvider()
    with pytest.raises(EmbeddingBackendUnavailable):
        provider.embed(["hello"])


def test_specter2_provider_raises_clear_error_without_dependency() -> None:
    provider = Specter2EmbeddingProvider()
    with pytest.raises(EmbeddingBackendUnavailable):
        provider.embed(["hello"])
