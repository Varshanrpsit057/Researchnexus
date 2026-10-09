"""Emailed one-time codes: six digits from the OS's CSPRNG, kept only as an
HMAC keyed with the server secret (so a copy of the database can't be
brute-forced back to live codes), valid for a few minutes, a few tries,
and exactly one successful use.

A challenge is what a code belongs to: signing up (the new account's name
and password hash wait in its payload until the email is confirmed),
signing in (after the password checked out), or resetting a password.
Decoys answer for an email that has no account (or, signing up, one that
already does) so a reply never says which emails are registered; their code
hash is of a random value nobody was sent.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import AuthChallengeORM


class Purpose(str, Enum):
    SIGNUP = "signup"
    LOGIN = "login"
    RESET = "reset"


class CodeError(Exception):
    """Why a code was not accepted. `code` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SecretMissing(RuntimeError):
    """RESEARCHNEXUS_SECRET_KEY is not set."""


@dataclass(frozen=True)
class Issued:
    challenge: AuthChallengeORM
    # the plain code, to put in the email; None for a decoy
    code: str | None


def _secret(settings: Settings) -> bytes:
    if not settings.secret_key:
        raise SecretMissing("RESEARCHNEXUS_SECRET_KEY is not set")
    return settings.secret_key.encode()


def _code_hash(settings: Settings, challenge_id: str, code: str) -> str:
    return hmac.new(_secret(settings), f"otp:{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue(
    db: Session,
    settings: Settings,
    *,
    purpose: Purpose,
    email: str,
    user_id: str | None,
    payload: dict | None = None,
    decoy: bool = False,
) -> Issued:
    challenge_id = f"chl_{secrets.token_hex(16)}"
    code = new_code()
    now = _now()
    row = AuthChallengeORM(
        id=challenge_id,
        purpose=purpose.value,
        email=email,
        user_id=user_id,
        # a decoy's hash is of a code nobody is sent
        code_hash=_code_hash(settings, challenge_id, new_code() + secrets.token_hex(8) if decoy else code),
        payload=payload or {},
        attempts=0,
        send_count=1,
        created_at=now,
        last_sent_at=now,
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
    )
    db.add(row)
    db.commit()
    return Issued(challenge=row, code=None if decoy else code)


def is_decoy(row: AuthChallengeORM) -> bool:
    if row.purpose == Purpose.SIGNUP.value:
        return not row.payload.get("password_hash")
    return row.user_id is None


def get_open(db: Session, challenge_id: str, purpose: Purpose | None = None) -> AuthChallengeORM:
    """The challenge, if it can still take a code."""
    row = db.get(AuthChallengeORM, challenge_id) if challenge_id.startswith("chl_") else None
    if row is None or (purpose is not None and row.purpose != purpose.value):
        raise CodeError("code_invalid", "This code isn't valid. Start again to get a new one.")
    if row.consumed_at is not None:
        raise CodeError("code_used", "This code was already used. Start again to get a new one.")
    if row.expires_at <= _now():
        raise CodeError("code_expired", "This code has expired. Send a new one.")
    return row


def verify(db: Session, settings: Settings, challenge_id: str, code: str, purpose: Purpose | None = None) -> AuthChallengeORM:
    """Accept the code (and use the challenge up) or say why not. Each wrong
    code uses one of the challenge's tries; the last one closes it."""
    row = get_open(db, challenge_id, purpose)
    if row.attempts >= settings.otp_max_attempts:
        raise CodeError("code_locked", "Too many wrong codes. Start again to get a new one.")
    code = code.strip().replace(" ", "")
    matches = len(code) == 6 and code.isdigit() and hmac.compare_digest(row.code_hash, _code_hash(settings, row.id, code))
    if not matches or is_decoy(row):
        # counted atomically: two guesses at once can't both take the last try
        db.execute(
            update(AuthChallengeORM)
            .where(AuthChallengeORM.id == row.id, AuthChallengeORM.attempts < settings.otp_max_attempts)
            .values(attempts=AuthChallengeORM.attempts + 1)
        )
        db.commit()
        db.refresh(row)
        left = settings.otp_max_attempts - row.attempts
        if left <= 0:
            raise CodeError("code_locked", "Too many wrong codes. Start again to get a new one.")
        raise CodeError("code_wrong", f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left.")
    # single use, even against two requests with the same right code at once
    used = db.execute(
        update(AuthChallengeORM)
        .where(AuthChallengeORM.id == row.id, AuthChallengeORM.consumed_at.is_(None))
        .values(consumed_at=_now())
    )
    db.commit()
    if not used.rowcount:  # type: ignore[attr-defined]
        raise CodeError("code_used", "This code was already used. Start again to get a new one.")
    db.refresh(row)
    return row


def reissue(db: Session, settings: Settings, challenge_id: str) -> Issued:
    """A fresh code for the same challenge (the old one stops working), once
    the cooldown has passed and while resends are left."""
    row = get_open(db, challenge_id)
    now = _now()
    wait = (row.last_sent_at + timedelta(seconds=settings.otp_resend_cooldown_seconds) - now).total_seconds()
    if wait > 0:
        raise CodeError("resend_too_soon", f"You can ask for a new code in {int(wait) + 1} seconds.")
    if row.send_count > settings.otp_max_resends:
        raise CodeError("resend_limit", "No more codes can be sent for this attempt. Start again.")
    code = new_code()
    row.code_hash = _code_hash(settings, row.id, code + (secrets.token_hex(8) if is_decoy(row) else ""))
    row.send_count += 1
    row.last_sent_at = now
    row.attempts = 0
    row.expires_at = now + timedelta(seconds=settings.otp_ttl_seconds)
    db.commit()
    return Issued(challenge=row, code=None if is_decoy(row) else code)


def resend_in(row: AuthChallengeORM, settings: Settings) -> int:
    wait = (row.last_sent_at + timedelta(seconds=settings.otp_resend_cooldown_seconds) - _now()).total_seconds()
    return max(0, int(wait) + (1 if wait > 0 else 0))


def resends_left(row: AuthChallengeORM, settings: Settings) -> int:
    return max(0, settings.otp_max_resends - (row.send_count - 1))
