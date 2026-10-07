"""What a discovery run is doing, as it happens (remediation Phase 8).

A discover job used to say only "discovery", then "ranking": a minute of
"Searching external sources..." with nothing to show whether anything was
happening. This records what really is -- which step is running and how
long each took, each strategy's state and how many papers it has returned,
each source's answers and failures (OpenAlex refusing anonymous search says
so, instead of the run just taking longer), and the papers found so far --
and hands it to a sink (the job row) at most twice a second, and at once
whenever a step starts or ends.

Nothing here is estimated: counts are of real answers, times are measured,
and the only limits shown are the ones the run enforces. The same record,
once the run is saved, becomes the run's `report`, so the results page can
say exactly what a partial run is missing and why.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.domain.candidate import DiscoveryStrategy, RawExternalRecord
from app.services.discovery.base import record_key
from app.services.normalize.canonical import to_normalized
from app.services.normalize.dedupe import SeedIdentity, matches_seed

# the run's steps, in the order they happen
STEPS = ("plan", "resolve", "search", "score", "save", "rank", "trail")
# the job's coarse `stage`, which older pages read
_STAGE_OF_STEP = {"rank": "ranking", "trail": "trail"}
SOURCE_OF_HOST = {
    "api.openalex.org": "openalex",
    "api.semanticscholar.org": "semantic_scholar",
    "export.arxiv.org": "arxiv",
    "arxiv.org": "arxiv",
    "www.ebi.ac.uk": "europe_pmc",
    "api.crossref.org": "crossref",
    "dblp.org": "dblp",
    "api.core.ac.uk": "core",
}
PREVIEW_SIZE = 8

Sink = Callable[[dict[str, Any]], None]
Clock = Callable[[], float]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryProgress:
    def __init__(self, sink: Sink | None = None, *, clock: Clock = time.monotonic, min_interval_s: float = 0.5) -> None:
        self._sink = sink
        self._clock = clock
        self._min_interval_s = min_interval_s
        self._started = clock()
        self._last_flush: float | None = None
        self.started_at = _now_iso()
        self.steps: dict[str, dict[str, Any]] = {s: {"state": "pending"} for s in STEPS}
        self._step_started: dict[str, float] = {}
        self.strategies: dict[str, dict[str, Any]] = {}
        self._strategy_started: dict[str, float] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self._seen: set[str] = set()
        self.preview: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self._seed: SeedIdentity | None = None

    def exclude_seed(self, seed: SeedIdentity) -> None:
        """Sources return the seed itself among its related work; it is never
        counted or shown as found (dedupe drops it from the run the same way)."""
        self._seed = seed

    # -- steps ------------------------------------------------------------------

    def begin(self, step: str, *, limit_s: float | None = None, total: int | None = None) -> None:
        """A step starts; `limit_s` is the most it is allowed to take (only a
        limit the run really enforces), `total` how many things it works through."""
        self._step_started[step] = self._clock()
        entry: dict[str, Any] = {"state": "running", "started_s": round(self.elapsed(), 1)}
        if limit_s is not None:
            entry["limit_s"] = round(limit_s, 1)
        if total is not None:
            entry["total"] = total
        self.steps[step] = entry
        self.flush(force=True)

    def end(self, step: str, *, state: str = "done", note: str | None = None, **counts: int) -> None:
        started = self._step_started.pop(step, None)
        entry = {k: v for k, v in self.steps.get(step, {}).items() if k in ("started_s", "limit_s", "total")}
        entry["state"] = state
        if started is not None:
            entry["seconds"] = round(self._clock() - started, 1)
        if note:
            entry["note"] = note
        entry.update(counts)
        self.steps[step] = entry
        self.flush(force=True)

    def skip(self, step: str, note: str) -> None:
        self.steps[step] = {"state": "skipped", "note": note}
        self.flush(force=True)

    # -- strategies ---------------------------------------------------------------

    def strategy_started(self, strategy: DiscoveryStrategy) -> None:
        self._strategy_started[strategy.value] = self._clock()
        self.strategies[strategy.value] = {"state": "running", "found": 0}
        self.flush()

    def strategy_finished(self, strategy: DiscoveryStrategy, *, state: str, found: int, notes: list[str] | None = None) -> None:
        """`state`: done, timed_out (stopped by its limit -- what it found is
        kept), failed, or empty (it ran but had nothing to work from)."""
        started = self._strategy_started.pop(strategy.value, None)
        entry: dict[str, Any] = {"state": state, "found": found}
        if started is not None:
            entry["seconds"] = round(self._clock() - started, 1)
        if notes:
            entry["notes"] = list(dict.fromkeys(notes))
        self.strategies[strategy.value] = entry
        self.flush(force=True)

    # -- sources and papers -----------------------------------------------------------

    def on_request(self, host: str, outcome: str, seconds: float) -> None:
        """Every request's outcome, per source (ExternalHttpClient's `on_request`)."""
        source = SOURCE_OF_HOST.get(host, host)
        entry = self.sources.setdefault(source, {"answered": 0, "failed": 0, "cached": 0})
        if outcome == "ok":
            entry["answered"] += 1
        elif outcome == "cached":
            entry["cached"] += 1
        else:
            entry["failed"] += 1
            entry["last_failure"] = outcome
        entry["seconds"] = round(entry.get("seconds", 0.0) + seconds, 1)
        self.flush()

    def found(self, strategy: DiscoveryStrategy, records: list[RawExternalRecord]) -> None:
        """Records a source just returned: the running count of distinct
        papers, and the first few of them as a preview. The preview is only
        what has arrived -- not yet ranked, and not a ranking."""
        running = self.strategies.get(strategy.value)
        new = 0
        for rec in records:
            if self._seed is not None and matches_seed(to_normalized(rec), self._seed):
                continue
            key = record_key(rec)
            if key in self._seen:
                continue
            self._seen.add(key)
            new += 1
            if len(self.preview) < PREVIEW_SIZE and rec.title.strip():
                self.preview.append({"title": rec.title.strip(), "year": rec.year, "source": rec.source.value})
        if running is not None and running.get("state") == "running":
            running["found"] = running.get("found", 0) + len(records)
        if new:
            self.flush()

    @property
    def distinct_found(self) -> int:
        return len(self._seen)

    def warn(self, *codes: str) -> None:
        for code in codes:
            if code not in self.warnings:
                self.warnings.append(code)

    # -- output -------------------------------------------------------------------

    def elapsed(self) -> float:
        return self._clock() - self._started

    def current_step(self) -> str | None:
        return next((s for s in STEPS if self.steps[s].get("state") == "running"), None)

    def snapshot(self) -> dict[str, Any]:
        step = self.current_step()
        return {
            "stage": _STAGE_OF_STEP.get(step or "", "discovery"),
            "step": step or "",
            "started_at": self.started_at,
            "elapsed_s": round(self.elapsed(), 1),
            "steps": {s: dict(v) for s, v in self.steps.items()},
            "strategies": {s: dict(v) for s, v in self.strategies.items()},
            "sources": {s: dict(v) for s, v in self.sources.items()},
            "found": self.distinct_found,
            "preview": list(self.preview),
            "warnings": list(self.warnings),
        }

    def report(self) -> dict[str, Any]:
        """What is kept on the saved run: how each step, strategy and source went."""
        snap = self.snapshot()
        return {k: snap[k] for k in ("started_at", "elapsed_s", "steps", "strategies", "sources", "warnings")}

    def flush(self, *, force: bool = False) -> None:
        if self._sink is None:
            return
        now = self._clock()
        if not force and self._last_flush is not None and now - self._last_flush < self._min_interval_s:
            return
        self._last_flush = now
        self._sink(self.snapshot())
