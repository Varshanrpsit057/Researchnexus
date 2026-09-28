from __future__ import annotations

from app.config import Settings
from app.services.discovery.pipeline import DiscoveryResult
from app.services.orchestrator.orchestrator import should_authorise_extra_citation_hop


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg,arg-type]


def _discovery_result(*, count_after_filter: int = 20, strategies_succeeded: list[str] | None = None) -> DiscoveryResult:
    return DiscoveryResult(
        run_id="run_1", status="ok",
        strategies_succeeded=strategies_succeeded if strategies_succeeded is not None else ["keyword", "citation", "semantic"],
        strategies_failed=[], count_raw=count_after_filter, count_after_dedupe=count_after_filter,
        count_after_filter=count_after_filter,
    )


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
