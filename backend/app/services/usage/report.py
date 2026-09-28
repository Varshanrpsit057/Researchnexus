"""What the language models were used for (remediation Phase 5).

Every figure is summed from the usage ledger (`llm_calls`, app/llm/usage.py):
the provider's own token counts for every call a user's key made --
answered, failed, or part of a chat turn that was never saved. Nothing is
estimated.

There is no cost. None of the providers says what a call cost, and with the
user's own key the price turns on things ResearchNexus can't see: the model's
list price that day, the account's tier or free quota, cache and off-peak
discounts. A price table kept here would go stale without anyone noticing,
so the report gives tokens and leaves the bill to the provider's console.

A range is a rolling window ending now ("the last 7 days" is the last
7 x 24 hours), reported with its exact start so a reader can see it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.db import repository as repo
from app.db.repository import UsageTotals

UsageRange = Literal["7d", "30d", "90d", "all"]
RANGE_DAYS: dict[str, int | None] = {"7d": 7, "30d": 30, "90d": 90, "all": None}


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at is not None else None


def _totals(t: UsageTotals) -> dict[str, int]:
    return {
        "calls": t.calls,
        "failed_calls": t.failed_calls,
        "unreported_calls": t.unreported_calls,
        "prompt_tokens": t.prompt_tokens,
        "cached_prompt_tokens": t.cached_prompt_tokens,
        "completion_tokens": t.completion_tokens,
        "reasoning_tokens": t.reasoning_tokens,
        "total_tokens": t.prompt_tokens + t.completion_tokens,
    }


def _largest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-r["total_tokens"], -r["calls"]))


def usage_report(
    db: Session,
    owner_id: str,
    *,
    range_key: UsageRange = "30d",
    workspace_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """The user's usage over `range_key`, in total and by feature and model
    -- and by workspace, unless the report is already for one workspace."""
    now = now or datetime.now(timezone.utc)
    days = RANGE_DAYS[range_key]
    since = now - timedelta(days=days) if days is not None else None

    def grouped(*by: str) -> list[tuple[tuple[str | None, ...], UsageTotals]]:
        return repo.summarize_llm_calls(db, owner_id, since=since, workspace_id=workspace_id, by=by)

    [(_, total)] = grouped()
    report: dict = {
        "range": {"key": range_key, "days": days, "since": _iso(since), "until": now.isoformat()},
        "workspace_id": workspace_id,
        "totals": _totals(total),
        "first_call_at": _iso(total.first_at),
        "last_call_at": _iso(total.last_at),
        "by_feature": _largest_first([{"feature": k[0], **_totals(t)} for k, t in grouped("feature")]),
        "by_model": _largest_first(
            [{"provider": k[0], "model": k[1], **_totals(t)} for k, t in grouped("provider", "model")]
        ),
    }
    if workspace_id is None:
        rows = grouped("workspace_id")
        titles = repo.workspace_titles(db, owner_id, [k[0] for k, _ in rows if k[0] is not None])
        report["by_workspace"] = _largest_first(
            [
                # no workspace: a paper's own profile or a discovery search plan;
                # no title: the workspace was deleted, its usage was not
                {"workspace_id": k[0], "title": titles.get(k[0]) if k[0] else None, **_totals(t)}
                for k, t in rows
            ]
        )
    return report
