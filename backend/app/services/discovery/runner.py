"""Bounded parallel discovery runner (Architecture §3 S6; Roadmap Phase 5:
"a parallel runner with per-strategy isolation and progress").

Two phases: retrieval strategies (keyword / query_expansion / citation)
run concurrently, their union becomes the pool, then scoring strategies
(semantic / semantic_doc) run concurrently over that pool. Every strategy
is wrapped in `asyncio.wait_for`; a raise or a timeout is isolated -- the
strategy is recorded as failed and the run continues (`status="partial"`).
`status="failed"` only when every strategy failed. Fusion / ranking is
Phase 6 and is NOT done here -- candidates come out in dedup order.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.domain.candidate import (
    CitationRelationship,
    DiscoveryStrategy,
    NormalizedCandidate,
    RawExternalRecord,
    RawSignalScores,
)
from app.services.discovery.base import (
    DiscoveryFilters,
    DiscoveryStrategyRunner,
    StrategyContext,
    StrategyResult,
)
from app.services.discovery.filter import apply_filters
from app.services.normalize.canonical import identity_keys
from app.services.normalize.dedupe import SeedIdentity, dedupe

_SIGNAL_FIELDS = set(RawSignalScores.model_fields)
# strategies whose hits come from the seed itself (its citations, its neighbours)
_SEED_LINKED = frozenset({DiscoveryStrategy.CITATION, DiscoveryStrategy.RECOMMENDATION})


@dataclass
class MergedCandidate:
    normalized: NormalizedCandidate
    discovery_methods: list[DiscoveryStrategy] = field(default_factory=list)
    raw_signals: RawSignalScores = field(default_factory=RawSignalScores)
    citation_relationship: CitationRelationship = CitationRelationship.NONE
    citation_hops: int | None = None
    filter_kept: bool = True
    filter_reasons: list[str] = field(default_factory=list)


@dataclass
class RunnerOutput:
    candidates: list[MergedCandidate]
    strategies_requested: list[DiscoveryStrategy]
    strategies_succeeded: list[DiscoveryStrategy]
    strategies_failed: list[DiscoveryStrategy]
    status: str
    warnings: list[str]
    count_raw: int
    count_after_dedupe: int
    count_after_filter: int


async def _run_one(
    strategy: DiscoveryStrategyRunner, ctx: StrategyContext, timeout_s: float
) -> tuple[DiscoveryStrategy, StrategyResult | BaseException, bool]:
    try:
        result = await asyncio.wait_for(strategy.run(ctx), timeout=timeout_s)
        return strategy.strategy, result, False
    except asyncio.TimeoutError as exc:  # noqa: UP041 - py3.10: asyncio.TimeoutError is not the builtin
        return strategy.strategy, exc, True
    except Exception as exc:  # noqa: BLE001 - isolation is the whole point
        return strategy.strategy, exc, False


async def _run_group(
    strategies: list[DiscoveryStrategyRunner], ctx: StrategyContext, timeout_s: float
) -> tuple[list[StrategyResult], list[DiscoveryStrategy], list[DiscoveryStrategy], list[str]]:
    results: list[StrategyResult] = []
    succeeded: list[DiscoveryStrategy] = []
    failed: list[DiscoveryStrategy] = []
    warnings: list[str] = []
    for name, outcome, timed_out in await asyncio.gather(
        *(_run_one(s, ctx, timeout_s) for s in strategies)
    ):
        if isinstance(outcome, StrategyResult):
            results.append(outcome)
            succeeded.append(name)
        else:
            failed.append(name)
            warnings.append(f"strategy_timeout:{name.value}" if timed_out else f"strategy_error:{name.value}")
    return results, succeeded, failed, warnings


async def run_discovery_strategies(
    ctx: StrategyContext,
    *,
    retrieval_strategies: list[DiscoveryStrategyRunner],
    scoring_strategies: list[DiscoveryStrategyRunner],
    per_strategy_timeout_s: float,
    seed_identity: SeedIdentity,
    filters: DiscoveryFilters,
) -> RunnerOutput:
    requested = [s.strategy for s in retrieval_strategies] + [s.strategy for s in scoring_strategies]

    retrieval_results, ok_a, fail_a, warn_a = await _run_group(retrieval_strategies, ctx, per_strategy_timeout_s)

    pool: list[RawExternalRecord] = [rec for res in retrieval_results for rec in res.records]
    ctx.candidate_pool = pool

    scoring_results, ok_b, fail_b, warn_b = await _run_group(scoring_strategies, ctx, per_strategy_timeout_s)

    all_results = retrieval_results + scoring_results
    all_records = [rec for res in all_results for rec in res.records]
    count_raw = len(all_records)

    deduped = dedupe(all_records, seed=seed_identity)
    count_after_dedupe = len(deduped.candidates)

    merged = [_merge_signals(cand, all_results) for cand in deduped.candidates]

    filtered = apply_filters(deduped.candidates, filters)
    dropped_hashes = {c.title_hash: reasons for c, reasons in filtered.dropped}
    for mc in merged:
        if mc.normalized.title_hash in dropped_hashes:
            mc.filter_kept = False
            mc.filter_reasons = dropped_hashes[mc.normalized.title_hash]
    warnings = [*warn_a, *warn_b]
    if len(merged) > ctx.budget.max_total_candidates:
        # The cap bites before any ranking, so cut by strength of evidence,
        # never blindly in discovery order: kept candidates first, then those
        # more strategies found, then those from the seed's own citation
        # neighbourhood or recommendations. The sort is stable otherwise.
        merged.sort(
            key=lambda mc: (
                not mc.filter_kept,
                -len(mc.discovery_methods),
                not any(m in _SEED_LINKED for m in mc.discovery_methods),
            )
        )
        merged = merged[: ctx.budget.max_total_candidates]
        warnings.append("budget_truncated")
    count_after_filter = sum(1 for mc in merged if mc.filter_kept)
    if ctx.budget.expired():
        warnings.append("deadline_reached")

    succeeded = ok_a + ok_b
    failed = fail_a + fail_b
    if not succeeded and not merged:
        status = "failed"
    elif failed or "budget_truncated" in warnings or "deadline_reached" in warnings:
        status = "partial"
    else:
        status = "succeeded"

    return RunnerOutput(
        candidates=merged,
        strategies_requested=requested,
        strategies_succeeded=succeeded,
        strategies_failed=failed,
        status=status,
        warnings=warnings,
        count_raw=count_raw,
        count_after_dedupe=count_after_dedupe,
        count_after_filter=count_after_filter,
    )


def _merge_signals(cand: NormalizedCandidate, results: list[StrategyResult]) -> MergedCandidate:
    keys = set(identity_keys(cand))
    mc = MergedCandidate(normalized=cand)
    signal_values: dict[str, float] = {}
    for res in results:
        contributed = False
        for sig_key, partial in res.signals.items():
            if sig_key not in keys:
                continue
            contributed = True
            for field_name, value in partial.items():
                if field_name in _SIGNAL_FIELDS:
                    signal_values[field_name] = max(signal_values.get(field_name, value), value)
        for sig_key, rel in res.citation_relationships.items():
            if sig_key in keys:
                contributed = True
                mc.citation_relationship = rel
                mc.citation_hops = res.citation_hops.get(sig_key, 1)
        if contributed and res.strategy not in mc.discovery_methods:
            mc.discovery_methods.append(res.strategy)
    mc.raw_signals = RawSignalScores(**signal_values)
    return mc
