from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.orchestrator import BudgetDecision, StageName, StageRun


def _run(**kw: object) -> StageRun:
    base: dict = {
        "id": "sr_1",
        "owner_id": "usr_1",
        "stage": StageName.INGEST,
        "tool": "run_ingestion",
        "input_hash": "abc123",
        "output_hash": "def456",
        "latency_ms": 12,
        "ok": True,
    }
    base.update(kw)
    return StageRun(**base)


def test_all_eleven_stage_names_are_defined() -> None:
    assert {s.value for s in StageName} == {
        "ingest", "profile", "discovery", "ranking", "trail", "workspace",
        "rag", "comparison", "gaps", "directions", "citations",
    }


def test_all_three_budget_decisions_are_defined() -> None:
    assert {d.value for d in BudgetDecision} == {"allow", "degrade", "block"}


def test_stage_run_requires_a_stage_from_the_enum() -> None:
    with pytest.raises(ValidationError):
        StageRun(
            id="sr_1", owner_id="usr_1", stage="not_a_stage", tool="x",  # type: ignore[arg-type]
            input_hash="a", output_hash="b", latency_ms=1, ok=True,
        )


def test_stage_run_defaults_are_workspace_and_job_agnostic() -> None:
    run = _run()
    assert run.workspace_id is None
    assert run.job_id is None
    assert run.tokens_prompt == 0
    assert run.tokens_completion == 0
    assert run.cost_usd == 0.0
    assert run.error is None


def test_stage_run_carries_no_prompt_or_response_bodies() -> None:
    # the domain model has no field wide enough to hold a prompt/response --
    # only hashes, counts, and a short error string (Data Model §13:
    # "No prompt/response bodies, no secrets").
    fields = set(StageRun.model_fields)
    assert fields == {
        "id", "owner_id", "workspace_id", "job_id", "stage", "tool",
        "input_hash", "output_hash", "tokens_prompt", "tokens_completion",
        "cost_usd", "latency_ms", "ok", "error", "ts",
    }


def test_a_failed_stage_run_carries_an_error_string() -> None:
    run = _run(ok=False, error="timeout")
    assert run.ok is False
    assert run.error == "timeout"


def test_workspace_and_job_scoped_run_round_trips_through_json() -> None:
    run = _run(workspace_id="ws_1", job_id="job_1", tokens_prompt=10, tokens_completion=5, cost_usd=0.001)
    restored = StageRun.model_validate(run.model_dump(mode="json"))
    assert restored == run
