"""`POST /api/v1/auth/session`, `GET /api/v1/me` -- Roadmap Task 1 (Phase 1);
API spec §2. Local-dev auth only: any password is accepted for an existing
or newly-created user identified by email (Architecture §7 risk note: keep
auth/session swappable behind `deps.get_current_user` -- a real IdP swap
only touches this router + app/security/jwt.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import repository as repo
from app.deps import AppSettings, CurrentUser, DbSession
from app.domain.user import LlmProvider, User
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
    # the provider LLM stages use right now: the default when its key works, else the first working key
    active_provider: str | None


def _me(db: DbSession, user: User) -> MeResponse:
    active = repo.pick_working_key(db, user.id, user.default_provider)
    return MeResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat(),
        has_working_llm_key=active is not None,
        default_provider=user.default_provider.value if user.default_provider else None,
        active_provider=active.provider.value if active else None,
    )


@router.get("/api/v1/me", response_model=MeResponse)
def get_me(current_user: CurrentUser, db: DbSession) -> MeResponse:
    return _me(db, current_user)


class MePatch(BaseModel):
    default_provider: str | None


@router.patch("/api/v1/me", response_model=MeResponse)
def patch_me(body: MePatch, current_user: CurrentUser, db: DbSession) -> MeResponse:
    provider: LlmProvider | None = None
    if body.default_provider is not None:
        try:
            provider = LlmProvider(body.default_provider)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "unsupported_provider", "message": f"unknown provider '{body.default_provider}'"}},
            ) from e
        if not any(k.provider == provider for k in repo.list_api_keys(db, current_user.id)):
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "no_key_for_provider", "message": f"save a {provider.value} key before making it the default"}},
            )
    user = repo.set_default_provider(db, current_user.id, provider)
    assert user is not None  # the current user exists
    return _me(db, user)
