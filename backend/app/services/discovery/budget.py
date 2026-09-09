"""Discovery budget guard (Roadmap Phase 5 risks: "Latency/cost blow-up ...
budget.py caps, config to disable strategies, per-strategy timeouts").

A plain value object -- strategies and the runner consult it; it does not
enforce anything itself. The final orchestrator's graceful-degradation
policy (Architecture §4) is out of Phase 5 scope; this just supplies the
limits.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class DiscoveryBudget:
    deadline_s: float = 90.0
    max_total_candidates: int = 200
    max_external_calls: int = 40
    clock: Callable[[], float] = time.monotonic
    _started_at: float = field(default=0.0, init=False)
    _external_calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._started_at = self.clock()

    def time_left(self) -> float:
        return max(0.0, self.deadline_s - (self.clock() - self._started_at))

    def expired(self) -> bool:
        return self.time_left() <= 0.0

    def can_call_external(self) -> bool:
        return self._external_calls < self.max_external_calls

    def record_external_call(self) -> None:
        self._external_calls += 1

    @property
    def external_calls_made(self) -> int:
        return self._external_calls
