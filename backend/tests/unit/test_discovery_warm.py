"""Candidates are embedded while the sources are still answering, on a worker
thread, so the scoring pass finds them done (remediation Phase 8)."""

from __future__ import annotations

import asyncio
import threading

import numpy as np

from app.retrieval.embeddings import FakeEmbeddingProvider
from app.services.discovery.warm import EmbeddingWarmer, worth_warming


class _CachingEmbedder:
    name = "caching-test"
    dimension = 4
    caches = True

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.threads: set[str] = set()

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        self.threads.add(threading.current_thread().name)
        return np.ones((len(texts), self.dimension), dtype="float32")


def test_only_an_embedder_that_keeps_its_vectors_is_warmed() -> None:
    assert worth_warming(_CachingEmbedder())
    assert not worth_warming(FakeEmbeddingProvider())
    assert not worth_warming(None)


def test_texts_are_embedded_once_each_off_the_event_loop() -> None:
    embedder = _CachingEmbedder()

    async def run() -> int:
        warmer = EmbeddingWarmer(embedder)
        warmer.start()
        warmer.add(["a", "b", ""])
        warmer.add(["b", "c"])  # "b" is already queued
        for _ in range(50):
            await asyncio.sleep(0.01)
            if warmer.embedded == 3:
                break
        await warmer.close()
        return warmer.embedded

    assert asyncio.run(run()) == 3
    assert sorted(t for call in embedder.calls for t in call) == ["a", "b", "c"]
    assert threading.main_thread().name not in embedder.threads


def test_a_failing_model_stops_warming_without_failing_the_run() -> None:
    class Broken(_CachingEmbedder):
        def embed(self, texts: list[str]) -> np.ndarray:
            raise RuntimeError("model gone")

    async def run() -> None:
        warmer = EmbeddingWarmer(Broken())
        warmer.start()
        warmer.add(["a"])
        await asyncio.sleep(0.05)
        await warmer.close()

    asyncio.run(run())  # no exception escapes
