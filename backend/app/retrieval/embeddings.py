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
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Protocol, cast

import numpy as np

from app.telemetry.logging import get_logger

_log = get_logger(__name__)


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


class FastEmbedEmbeddingProvider:
    """`BAAI/bge-small-en-v1.5` on ONNX Runtime via `fastembed` -- a real
    semantic embedding without torch (about 70 MB, fast on a laptop CPU).
    The discovery ranking's default: it scores a candidate's title+abstract
    against the seed, which is what separates related work from papers that
    merely share a word.

    Vectors are L2-normalised. Recently seen texts are cached, so ranking a
    run whose candidates were already embedded during discovery costs
    nothing extra -- and discovery embeds candidates ahead, while it waits on
    its sources (`caches` says doing so is worthwhile). One instance serves
    every discovery job, each on its own thread, so embedding is serialised."""

    name = "fastembed-bge-small"
    dimension = 384
    MODEL = "BAAI/bge-small-en-v1.5"
    caches = True
    _CACHE_MAX = 20000  # ~30 MB of vectors: discovery runs and workspace passages

    def __init__(self, cache_dir: str | Path | None = None, threads: int | None = None) -> None:
        self._cache_dir = str(cache_dir) if cache_dir is not None else None
        self._threads = threads
        self._model: object | None = None
        # the ONNX Runtime providers the model really runs on (e.g. ["CPUExecutionProvider"])
        self.execution_providers: list[str] = []
        self._vectors: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    def _load(self) -> object:
        if self._model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as e:
                raise EmbeddingBackendUnavailable("fastembed is not installed (pip install fastembed)") from e
            self._model = TextEmbedding(self.MODEL, cache_dir=self._cache_dir, threads=self._threads)
            try:  # what actually runs it -- a GPU is never claimed when the CPU did the work
                session = self._model.model.model  # type: ignore[attr-defined]
                self.execution_providers = list(session.get_providers())
            except AttributeError:
                self.execution_providers = []
            _log.info("embedding_model_loaded", model=self.MODEL, providers=self.execution_providers or ["unknown"], threads=self._threads)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            return self._embed(texts)

    def _embed(self, texts: list[str]) -> np.ndarray:
        missing = list(dict.fromkeys(t for t in texts if t not in self._vectors))
        if missing:
            model = self._load()
            vectors = np.asarray(list(model.embed(missing)), dtype="float32")  # type: ignore[attr-defined]
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            # cast: numpy's stubs differ across versions on this division's type
            vectors = cast(np.ndarray, vectors / np.where(norms == 0.0, 1.0, norms))
            for text, vec in zip(missing, vectors, strict=True):
                self._vectors[text] = vec
        out = np.stack([self._vectors[t] for t in texts]) if texts else np.zeros((0, self.dimension), "float32")
        for t in texts:
            self._vectors.move_to_end(t)
        while len(self._vectors) > self._CACHE_MAX:
            self._vectors.popitem(last=False)
        return out


_PROVIDERS: dict[str, type] = {
    "fake": FakeEmbeddingProvider,
    "minilm": MiniLMEmbeddingProvider,
    "specter2": Specter2EmbeddingProvider,
    "fastembed": FastEmbedEmbeddingProvider,
}


def get_embedding_provider(name: str, **kwargs: object) -> EmbeddingProvider:
    try:
        provider_cls = _PROVIDERS[name]
    except KeyError as e:
        raise ValueError(f"unknown embedding provider: {name!r} (known: {sorted(_PROVIDERS)})") from e
    return provider_cls(**kwargs)


_shared: dict[str, EmbeddingProvider] = {}
_shared_lock = threading.Lock()


def discovery_embedder(name: str, *, model_dir: Path, threads: int | None = None) -> EmbeddingProvider | None:
    """The process-wide embedder behind discovery's semantic signals, loaded
    once (discovery jobs run on worker threads, hence the lock). Returns
    None -- and the ranking falls back to its non-semantic signals -- when
    `name` is "none" or the model cannot be loaded (e.g. offline before its
    first download); the caller records that on the run."""
    if name == "none":
        return None
    with _shared_lock:
        provider = _shared.get(name)
        if provider is None:
            kwargs: dict[str, object] = {"cache_dir": model_dir, "threads": threads} if name == "fastembed" else {}
            try:
                provider = get_embedding_provider(name, **kwargs)
                provider.embed(["warm-up"])  # load now, so failure surfaces here, not mid-ranking
            except Exception:  # noqa: BLE001 - any load failure means "no semantic signals", not a crash
                return None
            _shared[name] = provider
        return provider
