"""Embedding provider interfaces (retrieval layer).

Phase 2 scope note: this module PREPARES the interface used by the
discovery and RAG phases (Roadmap P5/P9) -- it is not wired into the
ingestion pipeline yet. `FakeEmbeddingProvider` is dependency-free and
deterministic, used by tests and as a safe default. `MiniLMEmbeddingProvider`
and `Specter2EmbeddingProvider` lazy-import their (optional, heavy)
dependencies so importing this module never requires torch/sentence-
transformers to be installed; see pyproject.toml
`[project.optional-dependencies].embeddings` and docs/architecture/
ResearchNexus_Implementation_Architecture.md §7 (embedding choices).
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class EmbeddingBackendUnavailable(RuntimeError):
    """Raised when a real embedding backend's dependency is not installed."""


class FakeEmbeddingProvider:
    """Deterministic, dependency-free embedding provider.

    Not a real semantic embedding -- it hashes each text into a unit
    vector. Used for unit tests and as the Phase 2 default so retrieval
    code can be exercised end-to-end offline before a real model is wired
    in (Roadmap P5)."""

    name = "fake"
    dimension = 32

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._hash_vector(t) for t in texts]).astype("float32")

    def _hash_vector(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        repeats = (self.dimension // len(digest)) + 1
        raw = (digest * repeats)[: self.dimension]
        vector = (np.frombuffer(bytes(raw), dtype="uint8").astype("float32") - 127.5) / 127.5
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector


class MiniLMEmbeddingProvider:
    """`sentence-transformers/all-MiniLM-L6-v2`, lazy-loaded.

    Chunk-level embedding backbone recommended for discovery/RAG (review
    §11). Requires the optional `embeddings` extra."""

    name = "minilm"
    dimension = 384

    def __init__(self) -> None:
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise EmbeddingBackendUnavailable(
                    "sentence-transformers is not installed; install the 'embeddings' extra "
                    "(pip install -e '.[embeddings]')"
                ) from e
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        return np.asarray(model.encode(texts, normalize_embeddings=True), dtype="float32")  # type: ignore[attr-defined]


class Specter2EmbeddingProvider:
    """`allenai/specter2_base`, lazy-loaded.

    Document-level scholarly-similarity backbone recommended for
    related-paper discovery (review §9, §11, SciRepEval/SPECTER2). Requires
    the optional `embeddings` extra."""

    name = "specter2"
    dimension = 768

    def __init__(self) -> None:
        self._model: object | None = None
        self._tokenizer: object | None = None
        self._torch: object | None = None

    def _load(self) -> tuple[object, object, object]:
        if self._model is None:
            try:
                import torch
                from transformers import AutoModel, AutoTokenizer
            except ImportError as e:
                raise EmbeddingBackendUnavailable(
                    "transformers/torch is not installed; install the 'embeddings' extra "
                    "(pip install -e '.[embeddings]')"
                ) from e
            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained("allenai/specter2_base")
            self._model = AutoModel.from_pretrained("allenai/specter2_base")
        return self._model, self._tokenizer, self._torch

    def embed(self, texts: list[str]) -> np.ndarray:
        model, tokenizer, torch = self._load()
        inputs = tokenizer(texts, padding=True, truncation=True, return_tensors="pt", max_length=512)  # type: ignore[operator]
        with torch.no_grad():  # type: ignore[attr-defined]
            output = model(**inputs)  # type: ignore[operator]
        pooled = output.last_hidden_state.mean(dim=1)
        return pooled.numpy().astype("float32")


_PROVIDERS: dict[str, type] = {
    "fake": FakeEmbeddingProvider,
    "minilm": MiniLMEmbeddingProvider,
    "specter2": Specter2EmbeddingProvider,
}


def get_embedding_provider(name: str) -> EmbeddingProvider:
    try:
        provider_cls = _PROVIDERS[name]
    except KeyError as e:
        raise ValueError(f"unknown embedding provider: {name!r} (known: {sorted(_PROVIDERS)})") from e
    return provider_cls()
