"""Bounded parallel discovery runner (Architecture §3 S6; Roadmap Phase 5:
"a parallel runner with per-strategy isolation and progress").

Two phases: retrieval strategies (keyword / query_expansion / citation /
recommendation) run concurrently, their union becomes the pool, then scoring
strategies (semantic / semantic_doc) run concurrently over that pool. Every
strategy is wrapped in `asyncio.wait_for`; a raise or a timeout is isolated
and the run continues (`status="partial"`). A strategy stopped by its time
limit keeps what it had already found (remediation Phase 8 -- it used to
lose it all) and is listed as timed out; one that found nothing is failed.
`status="failed"` only when every strategy failed. Fusion / ranking is
Phase 6 and is NOT done here -- candidates come out in dedup order.

With a `DiscoveryProgress`, each phase and each strategy's state is
reported as it changes.
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
from app.services.discovery.progress import DiscoveryProgress
from app.services.normalize.canonical import identity_keys, to_normalized
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
    # stopped by their time limit; any that had found something are also in
    # strategies_succeeded, with what they found kept
    strategies_timed_out: list[DiscoveryStrategy] = field(default_factory=list)


async def _run_one(
    strategy: DiscoveryStrategyRunner, ctx: StrategyContext, timeout_s: float, progress: DiscoveryProgress | None
) -> tuple[DiscoveryStrategy, StrategyResult | BaseException, bool]:
    name = strategy.strategy
    if progress is not None:
        progress.strategy_started(name)
    outcome: StrategyResult | BaseException
    timed_out = False
    try:
        outcome = await asyncio.wait_for(strategy.run(ctx), timeout=timeout_s)
    except asyncio.TimeoutError as exc:  # noqa: UP041 - py3.10: asyncio.TimeoutError is not the builtin
        timed_out = True
        so_far = ctx.so_far.get(name)
        partial = so_far() if so_far is not None else None
        if partial is not None and partial.records:
            partial.notes.append(f"{name.value}_timed_out")
            outcome = partial
        else:
            outcome = exc
    except Exception as exc:  # noqa: BLE001 - isolation is the whole point
        outcome = exc
    if progress is not None:
        if isinstance(outcome, StrategyResult):
            progress.strategy_finished(
                name, state="timed_out" if timed_out else "done", found=len(outcome.records), notes=outcome.notes
            )
        else:
            reason = "timed_out" if timed_out else "error"
            progress.strategy_finished(name, state="failed", found=0, notes=[f"{name.value}_{reason}"])
    return name, outcome, timed_out


@dataclass
class _GroupOutcome:
    results: list[StrategyResult] = field(default_factory=list)
    succeeded: list[DiscoveryStrategy] = field(default_factory=list)
    failed: list[DiscoveryStrategy] = field(default_factory=list)
    timed_out: list[DiscoveryStrategy] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def _run_group(
    strategies: list[DiscoveryStrategyRunner], ctx: StrategyContext, timeout_s: float, progress: DiscoveryProgress | None
) -> _GroupOutcome:
    group = _GroupOutcome()
    for name, outcome, timed_out in await asyncio.gather(
        *(_run_one(s, ctx, timeout_s, progress) for s in strategies)
    ):
        if timed_out:
            group.timed_out.append(name)
            group.warnings.append(f"strategy_timeout:{name.value}")
        if isinstance(outcome, StrategyResult):
            group.results.append(outcome)
            group.succeeded.append(name)
        else:
            group.failed.append(name)
            if not timed_out:
                group.warnings.append(f"strategy_error:{name.value}")
    return group


async def run_discovery_strategies(
    ctx: StrategyContext,
    *,
    retrieval_strategies: list[DiscoveryStrategyRunner],
    scoring_strategies: list[DiscoveryStrategyRunner],
    per_strategy_timeout_s: float,
    seed_identity: SeedIdentity,
    filters: DiscoveryFilters,
    progress: DiscoveryProgress | None = None,
) -> RunnerOutput:
    requested = [s.strategy for s in retrieval_strategies] + [s.strategy for s in scoring_strategies]

    if progress is not None:
        progress.begin("search", limit_s=per_strategy_timeout_s)
    retrieval = await _run_group(retrieval_strategies, ctx, per_strategy_timeout_s, progress)
    if progress is not None:
        progress.end("search", state="done" if retrieval.succeeded else "failed", found=progress.distinct_found)
    if ctx.after_search is not None:
        await ctx.after_search()

    found: list[RawExternalRecord] = [rec for res in retrieval.results for rec in res.records]
    # Only the candidates under the run's cap are saved and ranked, so only
    # their records are scored (remediation Phase 8: scoring every record --
    # 500-700 on real seeds, about 50 ms each -- took up to 30 s, most of it
    # on candidates the cap then threw away). Each kept candidate is scored
    # on all its records, exactly as before; the cap's evidence order counts
    # only what retrieval found, and scoring adds the same to every kept one.
    pool = _records_of(_capped(_candidates(found, retrieval.results, seed_identity, filters), ctx), found)
    ctx.candidate_pool = pool

    if progress is not None:
        progress.begin("score", limit_s=per_strategy_timeout_s, total=len(pool))
    scoring = await _run_group(scoring_strategies, ctx, per_strategy_timeout_s, progress)
    if progress is not None:
        progress.end("score", state="done" if scoring.succeeded or not scoring_strategies else "failed")

    all_results = retrieval.results + scoring.results
    all_records = [rec for res in all_results for rec in res.records]
    # what the sources returned; a scoring pass re-reads those same records
    count_raw = len(found)

    merged = _candidates(all_records, all_results, seed_identity, filters)
    count_after_dedupe = len(merged)
    warnings = [*retrieval.warnings, *scoring.warnings]
    capped = _capped(merged, ctx)
    if len(capped) < len(merged):
        warnings.append("budget_truncated")
    merged = capped
    count_after_filter = sum(1 for mc in merged if mc.filter_kept)
    if ctx.budget.expired():
        warnings.append("deadline_reached")

    succeeded = retrieval.succeeded + scoring.succeeded
    failed = retrieval.failed + scoring.failed
    timed_out = retrieval.timed_out + scoring.timed_out
    if not succeeded and not merged:
        status = "failed"
    elif failed or timed_out or "budget_truncated" in warnings or "deadline_reached" in warnings:
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
        strategies_timed_out=timed_out,
    )


def _candidates(
    records: list[RawExternalRecord], results: list[StrategyResult], seed: SeedIdentity, filters: DiscoveryFilters
) -> list[MergedCandidate]:
    """Records deduped into candidates (in the order first found), each with
    its strategies' signals, and the filters' verdict on it."""
    deduped = dedupe(records, seed=seed)
    merged = [_merge_signals(cand, results) for cand in deduped.candidates]
    dropped = {c.title_hash: reasons for c, reasons in apply_filters(deduped.candidates, filters).dropped}
    for mc in merged:
        if mc.normalized.title_hash in dropped:
            mc.filter_kept = False
            mc.filter_reasons = dropped[mc.normalized.title_hash]
    return merged


def _capped(merged: list[MergedCandidate], ctx: StrategyContext) -> list[MergedCandidate]:
    """At most the run's candidate cap. The cap bites before any ranking, so
    it cuts by strength of evidence, never blindly in discovery order: kept
    candidates first, then those more strategies found, then those from the
    seed's own citation neighbourhood or recommendations. The sort is stable
    otherwise."""
    if len(merged) <= ctx.budget.max_total_candidates:
        return merged
    ordered = sorted(
        merged,
        key=lambda mc: (
            not mc.filter_kept,
            -len(mc.discovery_methods),
            not any(m in _SEED_LINKED for m in mc.discovery_methods),
        ),
    )
    return ordered[: ctx.budget.max_total_candidates]


def _records_of(candidates: list[MergedCandidate], records: list[RawExternalRecord]) -> list[RawExternalRecord]:
    """The records behind these candidates, in their original order."""
    keys: set[str] = {k for mc in candidates for k in identity_keys(mc.normalized)}
    return [rec for rec in records if keys.intersection(identity_keys(to_normalized(rec)))]


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
