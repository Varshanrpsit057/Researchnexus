"""Model usage (remediation Phase 5): `GET /api/v1/usage`.

The signed-in user's usage of their own model keys, from the usage ledger,
over a range (`7d`, `30d`, `90d` or `all`), for every workspace or one.
Tokens only -- see app/services/usage/report.py for why there is no cost.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import repository as repo
from app.db.session import get_db
from app.deps import CurrentUser
from app.services.usage.report import UsageRange, usage_report

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("")
def get_usage(
    db: DbSession,
    current_user: CurrentUser,
    range_key: Annotated[UsageRange, Query(alias="range")] = "30d",
    workspace_id: Annotated[str | None, Query()] = None,
) -> dict:
    if workspace_id is not None and repo.get_workspace(db, workspace_id, current_user.id) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "workspace not found"}})
    return usage_report(db, current_user.id, range_key=range_key, workspace_id=workspace_id)
