from __future__ import annotations

import numpy as np
import pytest

from app.retrieval.faiss_store import (
    FaissBackendUnavailable,
    FaissFlatIPIndex,
    NumpyFlatIPIndex,
    get_vector_index,
)


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.array(vec, dtype="float32")
    return arr / np.linalg.norm(arr)


def test_numpy_index_add_and_search_returns_nearest() -> None:
    index = NumpyFlatIPIndex(dimension=3)
    index.add(
        ["a", "b", "c"],
        np.stack([_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([0.9, 0.1, 0])]),
    )
    results = index.search(_unit([1, 0, 0]), k=2)
    assert results[0][0] == "a"
    assert [r[0] for r in results] == ["a", "c"]


def test_numpy_index_empty_search_returns_empty_list() -> None:
    index = NumpyFlatIPIndex(dimension=4)
    assert index.search(np.zeros(4, dtype="float32"), k=5) == []
    assert index.size() == 0


def test_numpy_index_rejects_wrong_dimension() -> None:
    index = NumpyFlatIPIndex(dimension=3)
    with pytest.raises(ValueError):
        index.add(["a"], np.zeros((1, 4), dtype="float32"))


def test_numpy_index_rejects_mismatched_ids_and_vectors() -> None:
    index = NumpyFlatIPIndex(dimension=3)
    with pytest.raises(ValueError):
        index.add(["a", "b"], np.zeros((1, 3), dtype="float32"))


def test_numpy_index_save_and_load_round_trip(tmp_path) -> None:
    index = NumpyFlatIPIndex(dimension=3)
    index.add(["a", "b"], np.stack([_unit([1, 0, 0]), _unit([0, 1, 0])]))
    path = str(tmp_path / "index")
    index.save(path)

    loaded = NumpyFlatIPIndex.load(path)
    assert loaded.size() == 2
    assert loaded.dimension == 3
    results = loaded.search(_unit([1, 0, 0]), k=1)
    assert results[0][0] == "a"


def test_faiss_backend_unavailable_raises_clear_error() -> None:
    index = FaissFlatIPIndex(dimension=3)
    with pytest.raises(FaissBackendUnavailable):
        index.add(["a"], np.zeros((1, 3), dtype="float32"))


def test_get_vector_index_factory_numpy() -> None:
    index = get_vector_index("numpy", dimension=8)
    assert isinstance(index, NumpyFlatIPIndex)
    assert index.dimension == 8


def test_get_vector_index_factory_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_vector_index("not-a-backend", dimension=8)
