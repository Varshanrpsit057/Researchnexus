"""`POST /api/v1/auth/session`, `GET /api/v1/me` -- Roadmap Task 1 (Phase 1);
API spec §2. Local-dev auth only: any password is accepted for an existing
or newly-created user identified by email (Architecture §7 risk note: keep
auth/session swappable behind `deps.get_current_user` -- a real IdP swap
only touches this router + app/security/jwt.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import repository as repo
from app.deps import AppSettings, CurrentUser, DbSession
from app.jobs.runner import new_id
from app.security.jwt import create_access_token

router = APIRouter(tags=["auth"])


class SessionRequest(BaseModel):
    email: str
    password: str


class SessionResponse(BaseModel):
    token: str
    expires_at: str


@router.post("/api/v1/auth/session", response_model=SessionResponse)
def create_session(body: SessionRequest, db: DbSession, settings: AppSettings) -> SessionResponse:
    user = repo.get_user_by_email(db, body.email)
    if user is None:
        user = repo.create_user(db, user_id=new_id("usr"), email=body.email)
    token = create_access_token(user_id=user.id, email=user.email, settings=settings)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes)).isoformat()
    return SessionResponse(token=token, expires_at=expires_at)


class MeResponse(BaseModel):
    id: str
    email: str
    created_at: str
    has_working_llm_key: bool
    default_provider: str | None


@router.get("/api/v1/me", response_model=MeResponse)
def get_me(current_user: CurrentUser, db: DbSession) -> MeResponse:
    has_key = repo.has_working_api_key(db, current_user.id)
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at.isoformat(),
        has_working_llm_key=has_key,
        default_provider=None,
    )
