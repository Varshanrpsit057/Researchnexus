"""Vector index interfaces (retrieval layer).

Phase 2 scope note: this module PREPARES the interface used by discovery
and RAG (Roadmap P5/P9) -- it is not populated by the ingestion pipeline
yet (chunks are created with `embedding_ref=None`). `NumpyFlatIPIndex` is
dependency-free and is today's default; `FaissFlatIPIndex` lazy-imports
`faiss-cpu` (see pyproject.toml `[project.optional-dependencies].faiss`)
and matches the project's chosen index type -- `IndexFlatIP` over
normalised vectors (docs/architecture/ResearchNexus_Implementation_
Architecture.md §7: "exact search fine at RN scale (tens-hundreds of
papers/workspace)").
"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class VectorIndex(Protocol):
    dimension: int

    def add(self, ids: list[str], vectors: np.ndarray) -> None: ...
    def search(self, query: np.ndarray, k: int) -> list[tuple[str, float]]: ...
    def size(self) -> int: ...
    def save(self, path: str) -> None: ...


class FaissBackendUnavailable(RuntimeError):
    """Raised when faiss-cpu is not installed."""


class NumpyFlatIPIndex:
    """Pure-numpy exact inner-product index. Correct reference
    implementation of `IndexFlatIP` semantics with zero extra dependencies
    -- vectors should be L2-normalised by the caller so inner product =
    cosine similarity."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self._ids: list[str] = []
        self._vectors: np.ndarray = np.zeros((0, dimension), dtype="float32")

    def add(self, ids: list[str], vectors: np.ndarray) -> None:
        vectors = np.asarray(vectors, dtype="float32")
        if vectors.ndim != 2 or vectors.shape[1] != self.dimension:
            raise ValueError(f"expected vectors of shape (N, {self.dimension}), got {vectors.shape}")
        if len(ids) != vectors.shape[0]:
            raise ValueError("ids and vectors must have the same length")
        self._ids.extend(ids)
        self._vectors = np.vstack([self._vectors, vectors])

    def search(self, query: np.ndarray, k: int) -> list[tuple[str, float]]:
        if self.size() == 0:
            return []
        query_vec = np.asarray(query, dtype="float32").reshape(1, -1)
        scores = (self._vectors @ query_vec.T).ravel()
        k = max(0, min(k, len(scores)))
        top_idx = np.argsort(-scores)[:k]
        return [(self._ids[i], float(scores[i])) for i in top_idx]

    def size(self) -> int:
        return len(self._ids)

    def save(self, path: str) -> None:
        # Ids are stored as a fixed-width unicode array (native numpy dtype)
        # rather than dtype=object, specifically so load() never needs
        # allow_pickle=True -- np.load on an untrusted/object-dtype .npz can
        # execute arbitrary code via pickle. This file is only ever written
        # by this class, but avoiding pickle costs nothing here.
        ids_array = np.array(self._ids, dtype="<U512")
        np.savez(path, ids=ids_array, vectors=self._vectors, dimension=np.array([self.dimension]))

    @classmethod
    def load(cls, path: str) -> NumpyFlatIPIndex:
        file_path = path if path.endswith(".npz") else path + ".npz"
        data = np.load(file_path)  # allow_pickle defaults to False -- see save()
        index = cls(dimension=int(data["dimension"][0]))
        index._ids = [str(x) for x in data["ids"]]
        index._vectors = data["vectors"].astype("float32")
        return index


class FaissFlatIPIndex:
    """`faiss.IndexFlatIP`-backed index, lazy-loaded. Requires the optional
    `faiss` extra. Not exercised by Phase 2's default test run."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self._index: object | None = None
        self._ids: list[str] = []

    def _ensure_index(self) -> object:
        if self._index is None:
            try:
                import faiss
            except ImportError as e:
                raise FaissBackendUnavailable(
                    "faiss-cpu is not installed; install the 'faiss' extra (pip install -e '.[faiss]')"
                ) from e
            self._index = faiss.IndexFlatIP(self.dimension)
        return self._index

    def add(self, ids: list[str], vectors: np.ndarray) -> None:
        index = self._ensure_index()
        index.add(np.asarray(vectors, dtype="float32"))  # type: ignore[attr-defined]
        self._ids.extend(ids)

    def search(self, query: np.ndarray, k: int) -> list[tuple[str, float]]:
        index = self._ensure_index()
        total = index.ntotal  # type: ignore[attr-defined]
        if total == 0:
            return []
        scores, positions = index.search(  # type: ignore[attr-defined]
            np.asarray(query, dtype="float32").reshape(1, -1), min(k, total)
        )
        return [(self._ids[i], float(s)) for s, i in zip(scores[0], positions[0], strict=True) if i >= 0]

    def size(self) -> int:
        return len(self._ids)

    def save(self, path: str) -> None:
        import faiss

        if self._index is not None:
            faiss.write_index(self._index, path)


_BACKENDS: dict[str, type] = {"numpy": NumpyFlatIPIndex, "faiss": FaissFlatIPIndex}


def get_vector_index(name: str, dimension: int) -> VectorIndex:
    try:
        backend_cls = _BACKENDS[name]
    except KeyError as e:
        raise ValueError(f"unknown vector index backend: {name!r} (known: {sorted(_BACKENDS)})") from e
    return backend_cls(dimension)
