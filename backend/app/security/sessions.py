"""Server-side sessions.

A session is a random 256-bit token. The browser keeps it in an httpOnly
cookie (page scripts can't read it); the database keeps only its SHA-256.
A session ends at `expires_at`, after `session_idle_hours` without use, or
when revoked (sign-out, a password change or reset, "sign out other
devices"). A new session is made on every successful sign-in and any
session the browser already had is revoked, so a session id planted before
sign-in is never the one that ends up signed in (session fixation).

CSRF: the session cookie is SameSite=Lax, and every state-changing request
authenticated by it must also carry `X-CSRF-Token`: an HMAC of the session
token under the server secret, handed to the page in a readable cookie.
Another site can make the browser send the cookie, but can't read it to
compute the header.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import AuthSessionORM

# refresh `last_seen_at` at most this often (each refresh is a write)
_TOUCH_EVERY = timedelta(minutes=5)


@dataclass(frozen=True)
class Authenticated:
    session_id: str
    user_id: str
    token: str


def cookie_names(settings: Settings) -> tuple[str, str]:
    """The session and CSRF cookie names. Over HTTPS they carry the __Host-
    prefix: the browser then only accepts them Secure, for this exact host,
    on every path -- a sibling subdomain can't plant or shadow them."""
    prefix = "__Host-" if settings.secure_cookies else ""
    return f"{prefix}rn_session", f"{prefix}rn_csrf"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(settings: Settings, session_token: str) -> str:
    secret = (settings.secret_key or "").encode()
    return hmac.new(secret, f"csrf:{session_token}".encode(), hashlib.sha256).hexdigest()


def csrf_ok(settings: Settings, session_token: str, header: str | None) -> bool:
    return bool(header) and bool(settings.secret_key) and hmac.compare_digest(csrf_token(settings, session_token), header or "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create(db: Session, settings: Settings, user_id: str, *, user_agent: str | None, ip: str | None) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    db.add(
        AuthSessionORM(
            id=f"ses_{secrets.token_hex(10)}",
            user_id=user_id,
            token_hash=_hash(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_max_age_hours),
            user_agent=(user_agent or "")[:255] or None,
            ip=(ip or "")[:64] or None,
        )
    )
    db.commit()
    return token


def resolve(db: Session, settings: Settings, token: str | None) -> Authenticated | None:
    """The live session behind a token, refreshing when it was last seen."""
    if not token or len(token) > 128:
        return None
    row = db.execute(select(AuthSessionORM).where(AuthSessionORM.token_hash == _hash(token))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    now = _now()
    if row.expires_at <= now or row.last_seen_at + timedelta(hours=settings.session_idle_hours) <= now:
        return None
    if now - row.last_seen_at >= _TOUCH_EVERY:
        row.last_seen_at = now
        db.commit()
    return Authenticated(session_id=row.id, user_id=row.user_id, token=token)


def revoke_token(db: Session, token: str | None) -> None:
    if not token or len(token) > 128:
        return
    db.execute(
        update(AuthSessionORM)
        .where(AuthSessionORM.token_hash == _hash(token), AuthSessionORM.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()


def revoke(db: Session, user_id: str, session_id: str) -> bool:
    done = db.execute(
        update(AuthSessionORM)
        .where(AuthSessionORM.id == session_id, AuthSessionORM.user_id == user_id, AuthSessionORM.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()
    return bool(done.rowcount)  # type: ignore[attr-defined]


def revoke_all(db: Session, user_id: str, *, except_session: str | None = None) -> int:
    stmt = update(AuthSessionORM).where(AuthSessionORM.user_id == user_id, AuthSessionORM.revoked_at.is_(None))
    if except_session is not None:
        stmt = stmt.where(AuthSessionORM.id != except_session)
    done = db.execute(stmt.values(revoked_at=_now()))
    db.commit()
    return int(done.rowcount)  # type: ignore[attr-defined]


def list_live(db: Session, settings: Settings, user_id: str) -> list[AuthSessionORM]:
    now = _now()
    rows = (
        db.execute(
            select(AuthSessionORM)
            .where(AuthSessionORM.user_id == user_id, AuthSessionORM.revoked_at.is_(None), AuthSessionORM.expires_at > now)
            .order_by(AuthSessionORM.last_seen_at.desc())
        )
        .scalars()
        .all()
    )
    idle = timedelta(hours=settings.session_idle_hours)
    return [r for r in rows if r.last_seen_at + idle > now]


def set_cookies(response: Response, settings: Settings, token: str) -> None:
    session_name, csrf_name = cookie_names(settings)
    max_age = settings.session_max_age_hours * 3600
    common = {"max_age": max_age, "path": "/", "secure": settings.secure_cookies, "samesite": "lax"}
    response.set_cookie(session_name, token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(csrf_name, csrf_token(settings, token), httponly=False, **common)  # type: ignore[arg-type]


def clear_cookies(response: Response, settings: Settings) -> None:
    for name in cookie_names(settings):
        response.delete_cookie(name, path="/", secure=settings.secure_cookies, samesite="lax")
