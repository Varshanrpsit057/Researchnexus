from __future__ import annotations

from app.config import Settings
from app.domain.candidate import DiscoveryStrategy
from app.domain.orchestrator import BudgetDecision
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.services.discovery.pipeline import DiscoveryOptions, DiscoveryResult
from app.services.orchestrator.budget import (
    decide_budget,
    degrade_discovery_options,
    degrade_top_k,
    estimate_cost_usd,
    should_authorise_extra_citation_hop,
)


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg,arg-type]


def _ws(*, budget: float = 5.0, used: float = 0.0) -> ResearchWorkspace:
    return ResearchWorkspace(
        workspace_id="ws_1", owner_id="usr_1", title="W", seed_paper_id="pap_1", seed_profile_id="prof_1",
        papers=[WorkspacePaper(workspace_id="ws_1", paper_id="pap_1", added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
        token_budget_usd=budget, cost_used_usd=used,
    )


def _discovery_result(*, count_after_filter: int = 20, strategies_succeeded: list[str] | None = None) -> DiscoveryResult:
    return DiscoveryResult(
        run_id="run_1", status="ok",
        strategies_succeeded=strategies_succeeded if strategies_succeeded is not None else ["keyword", "citation", "semantic"],
        strategies_failed=[], count_raw=count_after_filter, count_after_dedupe=count_after_filter,
        count_after_filter=count_after_filter,
    )


# --- estimate_cost_usd -------------------------------------------------


def test_estimate_cost_usd_uses_the_configured_blended_rate() -> None:
    settings = _settings(orchestrator_cost_per_1k_tokens_usd=0.002)
    assert estimate_cost_usd(500, 500, settings) == 0.002  # 1000 tokens * 0.002/1k
    assert estimate_cost_usd(0, 0, settings) == 0.0


# --- decide_budget -------------------------------------------------------


def test_decide_budget_allows_when_well_under_the_cap() -> None:
    settings = _settings()
    assert decide_budget(_ws(budget=5.0, used=0.0), settings) == BudgetDecision.ALLOW


def test_decide_budget_degrades_once_past_the_threshold_fraction() -> None:
    settings = _settings(orchestrator_budget_degrade_threshold=0.8)
    assert decide_budget(_ws(budget=5.0, used=4.5), settings) == BudgetDecision.DEGRADE


def test_decide_budget_blocks_once_spend_reaches_the_cap() -> None:
    settings = _settings()
    assert decide_budget(_ws(budget=5.0, used=5.0), settings) == BudgetDecision.BLOCK
    assert decide_budget(_ws(budget=5.0, used=6.0), settings) == BudgetDecision.BLOCK


def test_decide_budget_boundary_just_under_threshold_still_allows() -> None:
    settings = _settings(orchestrator_budget_degrade_threshold=0.8)
    assert decide_budget(_ws(budget=10.0, used=7.99), settings) == BudgetDecision.ALLOW


# --- degrade_discovery_options --------------------------------------------


def test_degrade_discovery_options_keeps_only_cheap_strategies() -> None:
    options = DiscoveryOptions(
        strategies=[DiscoveryStrategy.KEYWORD, DiscoveryStrategy.SEMANTIC, DiscoveryStrategy.SEMANTIC_DOC, DiscoveryStrategy.CITATION],
        max_results_per_strategy=25,
    )
    degraded = degrade_discovery_options(options)
    assert set(degraded.strategies or []) <= {DiscoveryStrategy.KEYWORD, DiscoveryStrategy.CITATION}
    assert degraded.strategies  # never empty
    assert degraded.max_results_per_strategy <= options.max_results_per_strategy


def test_degrade_discovery_options_falls_back_to_keyword_if_nothing_cheap_requested() -> None:
    options = DiscoveryOptions(strategies=[DiscoveryStrategy.SEMANTIC_DOC])
    degraded = degrade_discovery_options(options)
    assert degraded.strategies == [DiscoveryStrategy.KEYWORD]


# --- degrade_top_k ---------------------------------------------------------


def test_degrade_top_k_halves_but_never_below_the_floor() -> None:
    assert degrade_top_k(8) == 4
    assert degrade_top_k(4) == 4  # floor
    assert degrade_top_k(1) == 4  # never smaller than the floor


# --- should_authorise_extra_citation_hop -----------------------------------


def test_extra_hop_authorised_when_candidates_are_thin() -> None:
    settings = _settings(orchestrator_min_candidates_for_hop=5, orchestrator_min_strategy_diversity=2)
    thin = _discovery_result(count_after_filter=2, strategies_succeeded=["keyword", "citation"])
    assert should_authorise_extra_citation_hop(thin, settings) is True


def test_extra_hop_authorised_when_strategy_diversity_is_low() -> None:
    settings = _settings(orchestrator_min_candidates_for_hop=5, orchestrator_min_strategy_diversity=2)
    narrow = _discovery_result(count_after_filter=20, strategies_succeeded=["keyword"])
    assert should_authorise_extra_citation_hop(narrow, settings) is True


def test_extra_hop_not_authorised_for_a_healthy_result() -> None:
    settings = _settings(orchestrator_min_candidates_for_hop=5, orchestrator_min_strategy_diversity=2)
    healthy = _discovery_result(count_after_filter=20, strategies_succeeded=["keyword", "citation", "semantic"])
    assert should_authorise_extra_citation_hop(healthy, settings) is False


def test_extra_hop_boundary_exactly_at_the_minimum_is_not_authorised() -> None:
    settings = _settings(orchestrator_min_candidates_for_hop=5, orchestrator_min_strategy_diversity=2)
    boundary = _discovery_result(count_after_filter=5, strategies_succeeded=["keyword", "citation"])
    assert should_authorise_extra_citation_hop(boundary, settings) is False
