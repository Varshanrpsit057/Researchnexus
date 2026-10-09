"""Fixed-window rate limits kept in the database, so every server process
(and every container behind a load balancer) counts the same requests.

`hit` adds one to the key's counter for the current window and says whether
the request is still within the limit, and if not, how long until the
window turns. Keys name what is limited and by what, e.g.
"login:ip:203.0.113.7" or "otp-send:email:a@b.org"; emails are hashed so the
table holds no addresses.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import RateLimitORM


@dataclass(frozen=True)
class Limit:
    name: str
    max_hits: int
    window_s: int


@dataclass(frozen=True)
class RateResult:
    allowed: bool
    retry_after_s: int


# set from the settings at start (app/main.py): development may scale limits up
_scale = 1.0


def configure(scale: float) -> None:
    global _scale
    _scale = max(1.0, scale)


def _max_hits(limit: Limit) -> int:
    return int(limit.max_hits * _scale)


# Sign-in: tries per address, and failed passwords per account.
LOGIN_PER_IP = Limit("login:ip", 30, 15 * 60)
LOGIN_FAILURES_PER_EMAIL = Limit("login-fail:email", 10, 15 * 60)
# Codes sent (sign-up, sign-in, reset, resend): stops email bombing.
CODE_SENDS_PER_EMAIL = Limit("code-send:email", 8, 60 * 60)
CODE_SENDS_PER_IP = Limit("code-send:ip", 30, 60 * 60)
# Code guesses per address (each challenge also allows only a few).
CODE_CHECKS_PER_IP = Limit("code-check:ip", 40, 15 * 60)
# New accounts per address.
SIGNUPS_PER_IP = Limit("signup:ip", 10, 60 * 60)
# Live checks of the scholarly sources (each sends one request to every source).
SOURCE_CHECKS_PER_USER = Limit("sources-check:user", 6, 10 * 60)
# Password changes per account (each one checks the current password).
PASSWORD_CHANGES_PER_USER = Limit("password-change:user", 10, 60 * 60)


def subject(value: str) -> str:
    """A stable, address-free name for an email (or anything personal)."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]


def _window(now: datetime, window_s: int) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % window_s, tz=timezone.utc)


def hit(db: Session, limit: Limit, who: str, *, now: datetime | None = None) -> RateResult:
    now = now or datetime.now(timezone.utc)
    key = f"{limit.name}:{who}"[:255]
    start = _window(now, limit.window_s)
    for _ in range(2):
        updated = db.execute(
            update(RateLimitORM)
            .where(RateLimitORM.key == key, RateLimitORM.window_start == start)
            .values(count=RateLimitORM.count + 1)
        )
        if updated.rowcount:  # type: ignore[attr-defined]
            break
        try:
            db.add(RateLimitORM(key=key, window_start=start, count=1))
            db.flush()
            break
        except IntegrityError:  # another request made this window's row first
            db.rollback()
    count = db.execute(
        select(RateLimitORM.count).where(RateLimitORM.key == key, RateLimitORM.window_start == start)
    ).scalar_one()
    if random.random() < 0.02:  # now and then, forget windows that ended a day ago
        db.execute(delete(RateLimitORM).where(RateLimitORM.window_start < now - timedelta(days=1)))
    db.commit()
    retry = int((start + timedelta(seconds=limit.window_s) - now).total_seconds()) + 1
    return RateResult(allowed=count <= _max_hits(limit), retry_after_s=max(retry, 1))


def over(db: Session, limit: Limit, who: str) -> bool:
    """Whether the key is already at its limit (without adding a hit)."""
    return peek(db, limit, who) >= _max_hits(limit)


def peek(db: Session, limit: Limit, who: str, *, now: datetime | None = None) -> int:
    """How many hits the key has in the current window (without adding one)."""
    now = now or datetime.now(timezone.utc)
    key = f"{limit.name}:{who}"[:255]
    count = db.execute(
        select(RateLimitORM.count).where(RateLimitORM.key == key, RateLimitORM.window_start == _window(now, limit.window_s))
    ).scalar_one_or_none()
    return count or 0
