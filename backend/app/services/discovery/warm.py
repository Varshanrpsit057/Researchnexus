"""Embed candidates while the sources are still answering (remediation
Phase 8).

Measured on real seeds: the scoring pass embedded 230-300 texts in 15-16 s,
and only after every source had answered -- on the event loop, so nothing
else (not even the run's progress) could happen meanwhile. The relevance
model caches what it has embedded, so embedding each batch of candidates on
a worker thread as it arrives moves that work into the time the run spends
waiting on the network; the scoring pass that follows then finds its texts
already embedded. The vectors are the model's own either way: this changes
when they are computed, never what they are.
"""

from __future__ import annotations

import asyncio
import contextlib

from app.retrieval.embeddings import EmbeddingProvider
from app.telemetry.logging import get_logger

_log = get_logger(__name__)
# small batches: stopping waits for at most one to finish
_BATCH = 32


def worth_warming(embedder: EmbeddingProvider | None) -> bool:
    """Only an embedder that keeps what it embedded gains from embedding early."""
    return embedder is not None and bool(getattr(embedder, "caches", False))


class EmbeddingWarmer:
    def __init__(self, embedder: EmbeddingProvider) -> None:
        self._embedder = embedder
        self._queue: list[str] = []
        self._queued: set[str] = set()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.embedded = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._work())

    def add(self, texts: list[str]) -> None:
        for text in texts:
            if text.strip() and text not in self._queued:
                self._queued.add(text)
                self._queue.append(text)
        if self._queue:
            self._wake.set()

    async def _work(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._queue:
                batch, self._queue = self._queue[:_BATCH], self._queue[_BATCH:]
                try:
                    await asyncio.to_thread(self._embedder.embed, batch)
                except Exception:  # noqa: BLE001 - warming is only a head start; the scoring pass embeds for itself
                    _log.exception("discovery_embedding_warmup_failed")
                    return
                self.embedded += len(batch)

    async def close(self) -> None:
        """Stop embedding ahead (a batch already on its thread finishes there)."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
