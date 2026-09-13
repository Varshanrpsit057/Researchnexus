"""`BudgetGuard` (Architecture §4 actor table: "Deterministic; token/USD
counters -> degrade signals (fewer strategies, smaller k); hard stop at cap
-> notify user, offer raise"). Pure and deterministic -- no LLM, no DB.

BYOK means ResearchNexus never sees the user's real provider invoice, so
`estimate_cost_usd` is a deliberately simple, configurable blended rate
(`Settings.orchestrator_cost_per_1k_tokens_usd`) used only to compare
running spend against the workspace's own `token_budget_usd` cap -- not a
claim about real billing.
"""

from __future__ import annotations

from dataclasses import replace

from app.config import Settings
from app.domain.candidate import DiscoveryStrategy
from app.domain.orchestrator import BudgetDecision
from app.domain.workspace import ResearchWorkspace
from app.services.discovery.pipeline import DiscoveryOptions, DiscoveryResult

_CHEAP_STRATEGIES = (DiscoveryStrategy.KEYWORD, DiscoveryStrategy.CITATION)
_TOP_K_FLOOR = 4


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int, settings: Settings) -> float:
    total = prompt_tokens + completion_tokens
    return round((total / 1000) * settings.orchestrator_cost_per_1k_tokens_usd, 6)


def decide_budget(workspace: ResearchWorkspace, settings: Settings) -> BudgetDecision:
    if workspace.cost_used_usd >= workspace.token_budget_usd:
        return BudgetDecision.BLOCK
    if workspace.cost_used_usd >= workspace.token_budget_usd * settings.orchestrator_budget_degrade_threshold:
        return BudgetDecision.DEGRADE
    return BudgetDecision.ALLOW


def degrade_discovery_options(options: DiscoveryOptions) -> DiscoveryOptions:
    requested = options.strategies or []
    cheap = [s for s in requested if s in _CHEAP_STRATEGIES] or [DiscoveryStrategy.KEYWORD]
    return replace(
        options,
        strategies=cheap,
        max_results_per_strategy=min(options.max_results_per_strategy, 10),
    )


def degrade_top_k(k: int, *, floor: int = _TOP_K_FLOOR) -> int:
    return max(floor, k // 2)


def should_authorise_extra_citation_hop(result: DiscoveryResult, settings: Settings) -> bool:
    return (
        result.count_after_filter < settings.orchestrator_min_candidates_for_hop
        or len(result.strategies_succeeded) < settings.orchestrator_min_strategy_diversity
    )
