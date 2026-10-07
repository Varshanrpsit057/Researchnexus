"""Cross-cutting FastAPI dependencies (Roadmap Task 1 item 2): `get_db`,
`get_current_user` (a dev-JWT stub -- swap only this when a real IdP
arrives, per Architecture §7), and `get_llm_client` (BYOK provider
dispatch). No route depends on a concrete auth provider directly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db
from app.domain.user import LlmProvider, User
from app.llm.client import LLMClient
from app.llm.providers.gemini import GeminiClient
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.security.jwt import InvalidToken, decode_access_token

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    db: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=401, detail={"error": {"code": "unauthenticated", "message": "missing bearer token"}}
        )
    try:
        payload = decode_access_token(credentials.credentials, settings)
    except InvalidToken as e:
        raise HTTPException(
            status_code=401, detail={"error": {"code": "unauthenticated", "message": str(e)}}
        ) from e
    user = repo.get_user(db, payload.sub)
    if user is None:
        raise HTTPException(
            status_code=401, detail={"error": {"code": "unauthenticated", "message": "user not found"}}
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_optional_user(
    db: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> User | None:
    """The signed-in reader when the request says who it is, else None -- for
    routes open to anyone that still credit the reader (an upload lands in
    their library). A stale or unknown token reads as nobody, not an error."""
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials, settings)
    except InvalidToken:
        return None
    return repo.get_user(db, payload.sub)


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def get_llm_client(provider: LlmProvider) -> LLMClient:
    if provider == LlmProvider.GEMINI:
        return GeminiClient()
    return OpenAiCompatClient(provider)
