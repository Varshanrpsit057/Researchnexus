"""Dev JWT issuance/verification (Roadmap Task 1: "get_current_user stub
verifying a dev JWT"; Architecture §7 risk note: keep the auth provider
swappable behind deps.get_current_user). HS256 with a shared secret is a
deliberate MVP choice -- swapping to a real IdP (Cognito, etc.) later only
touches this module and app/routers/auth.py, not the rest of the app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import Settings


class JwtMisconfigured(RuntimeError):
    """Raised when RESEARCHNEXUS_JWT_SECRET is not set."""


class InvalidToken(Exception):
    """Raised for any token that fails signature, expiry, or claim checks."""


class TokenPayload(BaseModel):
    sub: str
    email: str


def _require_secret(settings: Settings) -> str:
    if not settings.jwt_secret:
        raise JwtMisconfigured("RESEARCHNEXUS_JWT_SECRET is not set")
    return settings.jwt_secret


def create_access_token(*, user_id: str, email: str, settings: Settings) -> str:
    secret = _require_secret(settings)
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(claims, secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> TokenPayload:
    secret = _require_secret(settings)
    try:
        claims = jwt.decode(token, secret, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise InvalidToken(str(e)) from e
    sub = claims.get("sub")
    email = claims.get("email")
    if not sub or not email:
        raise InvalidToken("token missing required claims")
    return TokenPayload(sub=sub, email=email)
