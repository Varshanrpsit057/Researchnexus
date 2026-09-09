from __future__ import annotations

from app.services.discovery.budget import DiscoveryBudget


def test_time_left_and_expiry_with_injected_clock() -> None:
    now = {"t": 100.0}
    budget = DiscoveryBudget(deadline_s=30.0, clock=lambda: now["t"])
    assert budget.time_left() == 30.0
    assert budget.expired() is False
    now["t"] = 125.0
    assert budget.time_left() == 5.0
    now["t"] = 140.0
    assert budget.time_left() == 0.0
    assert budget.expired() is True


def test_external_call_cap() -> None:
    budget = DiscoveryBudget(max_external_calls=2)
    assert budget.can_call_external() is True
    budget.record_external_call()
    budget.record_external_call()
    assert budget.can_call_external() is False


def test_total_candidate_cap_is_exposed() -> None:
    budget = DiscoveryBudget(max_total_candidates=50)
    assert budget.max_total_candidates == 50
