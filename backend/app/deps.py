"""Cross-cutting FastAPI dependencies: `get_db`, the signed-in reader
(`get_auth` / `CurrentUser`), and `get_llm_client` (BYOK provider
dispatch). No route depends on a concrete auth mechanism directly.

A request is signed in by a session token: from the session cookie (the
browser), or as `Authorization: Bearer <token>` (scripts and tests; a
browser never adds that header by itself, so it needs no CSRF check). A
state-changing request signed in by the cookie must carry the CSRF header
(app/security/sessions.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db
from app.domain.user import LlmProvider, User
from app.llm.client import LLMClient
from app.llm.providers.gemini import GeminiClient
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.security import sessions

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AuthContext:
    user: User
    session_id: str
    token: str
    via: Literal["cookie", "bearer"]


def _unauthenticated(message: str) -> HTTPException:
    return HTTPException(status_code=401, detail={"error": {"code": "unauthenticated", "message": message}})


def session_token(request: Request, settings: Settings) -> tuple[str | None, Literal["cookie", "bearer"]]:
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip() or None, "bearer"
    return request.cookies.get(sessions.cookie_names(settings)[0]), "cookie"


def authenticate(request: Request, db: Session, settings: Settings) -> AuthContext | None:
    token, via = session_token(request, settings)
    found = sessions.resolve(db, settings, token)
    if found is None:
        return None
    user = repo.get_user(db, found.user_id)
    if user is None:
        return None
    request.state.user_id = user.id  # for the access log
    return AuthContext(user=user, session_id=found.session_id, token=found.token, via=via)


def get_auth(request: Request, db: DbSession, settings: AppSettings) -> AuthContext:
    ctx = authenticate(request, db, settings)
    if ctx is None:
        raise _unauthenticated("Sign in to continue.")
    if (
        ctx.via == "cookie"
        and request.method not in _SAFE_METHODS
        and not sessions.csrf_ok(settings, ctx.token, request.headers.get("x-csrf-token"))
    ):
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "csrf_failed", "message": "This request was missing its security token. Reload the page and try again."}},
        )
    return ctx


Auth = Annotated[AuthContext, Depends(get_auth)]


def get_current_user(ctx: Auth) -> User:
    return ctx.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_llm_client(provider: LlmProvider) -> LLMClient:
    if provider == LlmProvider.GEMINI:
        return GeminiClient()
    return OpenAiCompatClient(provider)
