"""Latency measurement for `stage_runs` rows (Roadmap Phase 14: "wired
into every tool"). Deliberately tiny: wall-clock elapsed time only -- no
sampling, no external dependency.
"""

from __future__ import annotations

import time
from types import TracebackType


class StageTimer:
    def __init__(self) -> None:
        self._start: float | None = None
        self.elapsed_ms: int | None = None

    def __enter__(self) -> StageTimer:
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._start is not None
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)
