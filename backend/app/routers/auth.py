"""Sign-up, sign-in with an emailed code, password reset, sessions, and the
account (`/api/v1/me`).

Every way in ends with a six-digit code sent to the account's email; only a
correct code makes a session (app/security/codes.py, sessions.py):

    sign up   POST /auth/signup {name, email, password}  -> code to the email
              POST /auth/verify {challenge_id, code}     -> account + session
    sign in   POST /auth/login {email, password}         -> code to the email
              POST /auth/verify {challenge_id, code}     -> session
    reset     POST /auth/password/forgot {email}         -> code to the email
              POST /auth/password/reset {challenge_id, code, password} -> session

Replies never say whether an email has an account: sign-up with a taken
email and a reset for an unknown one answer exactly like the real thing
(the owner of a taken email is told by email instead), and a wrong email
fails sign-in exactly like a wrong password, in the same time.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import Settings
from app.db import repository as repo
from app.db.models import AuthChallengeORM
from app.deps import AppSettings, Auth, CurrentUser, DbSession, authenticate, session_token
from app.domain.user import LlmProvider, User
from app.jobs.runner import new_id
from app.security import codes, rate_limit, sessions
from app.security.codes import CodeError, Purpose
from app.security.passwords import (
    PasswordPolicyError,
    check_policy,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.services import mail
from app.telemetry.logging import get_logger

router = APIRouter(tags=["auth"])
_log = get_logger("app.auth")

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")


# --- helpers -----------------------------------------------------------------


def _error(status: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}}, headers=headers)


def _clean_email(raw: str) -> str:
    email = raw.strip()
    if len(email) > 254 or not _EMAIL.match(email):
        raise _error(422, "invalid_email", "Enter a valid email address.")
    return email


def _ip(request: Request) -> str:
    # behind a load balancer, uvicorn's --proxy-headers puts the client's address here
    return request.client.host if request.client else "unknown"


def _limit(db: DbSession, limit: rate_limit.Limit, who: str) -> None:
    result = rate_limit.hit(db, limit, who)
    if not result.allowed:
        _log.warning("auth_rate_limited", limit=limit.name)
        minutes = max(1, round(result.retry_after_s / 60))
        raise _error(
            429,
            "rate_limited",
            f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
            headers={"Retry-After": str(result.retry_after_s)},
        )


def _masked(email: str) -> str:
    local, _, domain = email.partition("@")
    shown = local[:1] if len(local) <= 3 else local[:2]
    return f"{shown}{'•' * max(3, min(len(local) - len(shown), 8))}@{domain}"


class ChallengeResponse(BaseModel):
    challenge_id: str
    purpose: Literal["signup", "login", "reset"]
    # where the code went, partly hidden
    destination: str
    expires_in: int
    resend_in: int
    resends_left: int


def _challenge_json(row: AuthChallengeORM, settings: Settings) -> ChallengeResponse:
    now = datetime.now(timezone.utc)
    return ChallengeResponse(
        challenge_id=row.id,
        purpose=row.purpose,  # type: ignore[arg-type]
        destination=_masked(row.email),
        expires_in=max(0, int((row.expires_at - now).total_seconds())),
        resend_in=codes.resend_in(row, settings),
        resends_left=codes.resends_left(row, settings),
    )


def _send(settings: Settings, message: mail.Mail) -> None:
    """Send now, and tell the reader if it couldn't go."""
    try:
        mail.send(settings, message)
    except mail.MailError as e:
        _log.error("email_undeliverable", purpose=message.purpose, error=str(e))
        raise _error(503, "email_unavailable", "We couldn't send the email just now. Try again in a minute.") from e


def _send_quietly(settings: Settings, message: mail.Mail) -> None:
    """Send after the reply (when the reply mustn't depend on whether an
    email went out); a failure is logged."""
    try:
        mail.send(settings, message)
    except mail.MailError as e:
        _log.error("email_undeliverable", purpose=message.purpose, error=str(e))


def _code_error(e: CodeError) -> HTTPException:
    status = 429 if e.code in ("resend_too_soon",) else 400
    return _error(status, e.code, e.message)


def _start_session(request: Request, response: Response, db: DbSession, settings: Settings, user_id: str) -> None:
    """A new session for this browser. Any session it already had is
    revoked first, so a session id planted before sign-in is never the one
    signed in (session fixation)."""
    old, _ = session_token(request, settings)
    sessions.revoke_token(db, old)
    token = sessions.create(db, settings, user_id, user_agent=request.headers.get("user-agent"), ip=_ip(request))
    sessions.set_cookies(response, settings, token)


# --- the account --------------------------------------------------------------


class MeResponse(BaseModel):
    id: str
    email: str
    name: str | None
    email_verified: bool
    has_password: bool
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
        name=user.name,
        email_verified=user.email_verified_at is not None,
        has_password=user.has_password,
        created_at=user.created_at.isoformat(),
        has_working_llm_key=active is not None,
        default_provider=user.default_provider.value if user.default_provider else None,
        active_provider=active.provider.value if active else None,
    )


class SignedIn(BaseModel):
    user: MeResponse


# --- sign up ------------------------------------------------------------------


class SignupBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


@router.post("/api/v1/auth/signup", response_model=ChallengeResponse, status_code=202)
def signup(body: SignupBody, request: Request, db: DbSession, settings: AppSettings) -> ChallengeResponse:
    ip = _ip(request)
    email = _clean_email(body.email)
    name = " ".join(body.name.split())
    if not name:
        raise _error(422, "invalid_name", "Enter your name.")
    try:
        check_policy(body.password, email=email)
    except PasswordPolicyError as e:
        raise _error(422, "weak_password", str(e)) from e
    allowed = [d.strip().lower().lstrip("@") for d in settings.signup_allowed_domains if d.strip()]
    domain = email.rpartition("@")[2].lower()
    if allowed and not any(domain == d or domain.endswith(f".{d}") for d in allowed):
        raise _error(403, "signup_restricted", f"New accounts here are for addresses at {', '.join(allowed)}.")
    _limit(db, rate_limit.SIGNUPS_PER_IP, ip)
    _limit(db, rate_limit.CODE_SENDS_PER_IP, ip)
    _limit(db, rate_limit.CODE_SENDS_PER_EMAIL, rate_limit.subject(email))

    # hashed either way, so a taken email answers in the same time
    password_hash = hash_password(body.password)
    existing = repo.find_user_for_sign_in(db, email)
    if existing is not None:
        issued = codes.issue(db, settings, purpose=Purpose.SIGNUP, email=existing.email, user_id=None, decoy=True)
        _send(settings, mail.account_exists_mail(existing.email, settings.public_app_url.rstrip("/")))
        _log.info("auth_signup_existing_email", ip=ip)
    else:
        issued = codes.issue(
            db,
            settings,
            purpose=Purpose.SIGNUP,
            email=email.lower(),
            user_id=None,
            payload={"name": name, "password_hash": password_hash},
        )
        assert issued.code is not None
        _send(settings, mail.code_mail("signup", email.lower(), issued.code, ttl_s=settings.otp_ttl_seconds, name=name))
        _log.info("auth_signup_started", ip=ip)
    return _challenge_json(issued.challenge, settings)


# --- sign in ------------------------------------------------------------------


class LoginBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


_BAD_LOGIN = (
    "That email and password don't match an account. If your account was made before ResearchNexus had "
    "passwords, choose \"Forgot password\" to set one."
)


@router.post("/api/v1/auth/login", response_model=ChallengeResponse)
def login(body: LoginBody, request: Request, db: DbSession, settings: AppSettings) -> ChallengeResponse:
    ip = _ip(request)
    email = _clean_email(body.email)
    who = rate_limit.subject(email)
    _limit(db, rate_limit.LOGIN_PER_IP, ip)
    if rate_limit.over(db, rate_limit.LOGIN_FAILURES_PER_EMAIL, who):
        _limit(db, rate_limit.LOGIN_FAILURES_PER_EMAIL, who)  # over the limit: answers 429 with when to retry

    user = repo.find_user_for_sign_in(db, email)
    stored = repo.user_password_hash(db, user.id) if user is not None else None
    if user is None or not verify_password(stored, body.password):
        rate_limit.hit(db, rate_limit.LOGIN_FAILURES_PER_EMAIL, who)
        _log.warning("auth_login_failed", ip=ip, account=who[:12])
        raise _error(401, "invalid_credentials", _BAD_LOGIN)
    assert stored is not None
    if needs_rehash(stored):
        repo.set_user_password(db, user.id, hash_password(body.password), verify_email=False)

    _limit(db, rate_limit.CODE_SENDS_PER_IP, ip)
    _limit(db, rate_limit.CODE_SENDS_PER_EMAIL, who)
    issued = codes.issue(db, settings, purpose=Purpose.LOGIN, email=user.email, user_id=user.id)
    assert issued.code is not None
    _send(settings, mail.code_mail("login", user.email, issued.code, ttl_s=settings.otp_ttl_seconds, name=user.name))
    _log.info("auth_login_code_sent", ip=ip, user_id=user.id)
    return _challenge_json(issued.challenge, settings)


class VerifyBody(BaseModel):
    challenge_id: str = Field(max_length=80)
    code: str = Field(max_length=20)


@router.post("/api/v1/auth/verify", response_model=SignedIn)
def verify(body: VerifyBody, request: Request, response: Response, db: DbSession, settings: AppSettings) -> SignedIn:
    """Finish signing up or signing in with the emailed code. This is the
    only place (with a password reset) a session is made."""
    _limit(db, rate_limit.CODE_CHECKS_PER_IP, _ip(request))
    try:
        purpose = Purpose(codes.get_open(db, body.challenge_id).purpose)
        if purpose == Purpose.RESET:
            raise CodeError("code_invalid", "This code is for resetting a password.")
        row = codes.verify(db, settings, body.challenge_id, body.code, purpose)
    except CodeError as e:
        if e.code in ("code_wrong", "code_locked"):
            _log.warning("auth_code_rejected", ip=_ip(request), reason=e.code)
        raise _code_error(e) from e

    if row.purpose == Purpose.SIGNUP.value:
        if repo.find_user_for_sign_in(db, row.email) is not None:
            raise _error(409, "email_taken", "An account with this email was created meanwhile. Sign in instead.")
        user = repo.create_user(
            db,
            user_id=new_id("usr"),
            email=row.email,
            name=row.payload.get("name"),
            password_hash=row.payload["password_hash"],
            email_verified_at=datetime.now(timezone.utc),
        )
        _log.info("auth_signup_completed", user_id=user.id)
    else:
        assert row.user_id is not None
        repo.mark_email_verified(db, row.user_id)
        found = repo.get_user(db, row.user_id)
        if found is None:
            raise _error(400, "code_invalid", "This account no longer exists.")
        user = found
        _log.info("auth_login_completed", user_id=user.id)
    _start_session(request, response, db, settings, user.id)
    return SignedIn(user=_me(db, user))


class ResendBody(BaseModel):
    challenge_id: str = Field(max_length=80)


@router.post("/api/v1/auth/resend", response_model=ChallengeResponse)
def resend(body: ResendBody, request: Request, db: DbSession, settings: AppSettings) -> ChallengeResponse:
    _limit(db, rate_limit.CODE_SENDS_PER_IP, _ip(request))
    try:
        row = codes.get_open(db, body.challenge_id)
        _limit(db, rate_limit.CODE_SENDS_PER_EMAIL, rate_limit.subject(row.email))
        issued = codes.reissue(db, settings, body.challenge_id)
    except CodeError as e:
        raise _code_error(e) from e
    if issued.code is not None:
        name = issued.challenge.payload.get("name")
        if issued.challenge.user_id:
            owner = repo.get_user(db, issued.challenge.user_id)
            name = owner.name if owner else None
        _send(settings, mail.code_mail(issued.challenge.purpose, issued.challenge.email, issued.code, ttl_s=settings.otp_ttl_seconds, name=name))
    return _challenge_json(issued.challenge, settings)


# --- password reset -----------------------------------------------------------


class ForgotBody(BaseModel):
    email: str = Field(max_length=320)


@router.post("/api/v1/auth/password/forgot", response_model=ChallengeResponse, status_code=202)
def forgot_password(body: ForgotBody, request: Request, background: BackgroundTasks, db: DbSession, settings: AppSettings) -> ChallengeResponse:
    ip = _ip(request)
    email = _clean_email(body.email)
    _limit(db, rate_limit.CODE_SENDS_PER_IP, ip)
    _limit(db, rate_limit.CODE_SENDS_PER_EMAIL, rate_limit.subject(email))
    user = repo.find_user_for_sign_in(db, email)
    issued = codes.issue(
        db,
        settings,
        purpose=Purpose.RESET,
        email=user.email if user else email.lower(),
        user_id=user.id if user else None,
        decoy=user is None,
    )
    if user is not None and issued.code is not None:
        # sent after the reply, so the reply takes as long with or without an account
        background.add_task(_send_quietly, settings, mail.code_mail("reset", user.email, issued.code, ttl_s=settings.otp_ttl_seconds, name=user.name))
    _log.info("auth_reset_requested", ip=ip)
    return _challenge_json(issued.challenge, settings)


class ResetBody(BaseModel):
    challenge_id: str = Field(max_length=80)
    code: str = Field(max_length=20)
    password: str = Field(max_length=1024)


@router.post("/api/v1/auth/password/reset", response_model=SignedIn)
def reset_password(
    body: ResetBody, request: Request, response: Response, background: BackgroundTasks, db: DbSession, settings: AppSettings
) -> SignedIn:
    """A new password from the emailed code. Every other session ends; this
    browser is signed in (the code proved the email, the password is new)."""
    _limit(db, rate_limit.CODE_CHECKS_PER_IP, _ip(request))
    try:
        open_row = codes.get_open(db, body.challenge_id, Purpose.RESET)
        try:  # checked before the code, so a weak password doesn't use the code up
            check_policy(body.password, email=open_row.email)
        except PasswordPolicyError as e:
            raise _error(422, "weak_password", str(e)) from e
        row = codes.verify(db, settings, body.challenge_id, body.code, Purpose.RESET)
    except CodeError as e:
        raise _code_error(e) from e
    assert row.user_id is not None
    user = repo.set_user_password(db, row.user_id, hash_password(body.password), verify_email=True)
    if user is None:
        raise _error(400, "code_invalid", "This account no longer exists.")
    sessions.revoke_all(db, user.id)
    _start_session(request, response, db, settings, user.id)
    background.add_task(_send_quietly, settings, mail.password_changed_mail(user.email, settings.public_app_url.rstrip("/")))
    _log.info("auth_password_reset", user_id=user.id)
    return SignedIn(user=_me(db, user))


# --- signed in ------------------------------------------------------------------


@router.post("/api/v1/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DbSession, settings: AppSettings) -> Response:
    token, _ = session_token(request, settings)
    sessions.revoke_token(db, token)
    sessions.clear_cookies(response, settings)
    response.status_code = 204
    return response


class SessionJson(BaseModel):
    id: str
    current: bool
    created_at: str
    last_seen_at: str
    user_agent: str | None
    ip: str | None


@router.get("/api/v1/auth/sessions")
def list_sessions(auth: Auth, db: DbSession, settings: AppSettings) -> dict[str, list[SessionJson]]:
    rows = sessions.list_live(db, settings, auth.user.id)
    return {
        "sessions": [
            SessionJson(
                id=r.id,
                current=r.id == auth.session_id,
                created_at=r.created_at.isoformat(),
                last_seen_at=r.last_seen_at.isoformat(),
                user_agent=r.user_agent,
                ip=r.ip,
            )
            for r in rows
        ]
    }


@router.delete("/api/v1/auth/sessions/{session_id}", status_code=204)
def revoke_session(session_id: str, auth: Auth, response: Response, db: DbSession, settings: AppSettings) -> Response:
    if not sessions.revoke(db, auth.user.id, session_id):
        raise _error(404, "not_found", "That session has already ended.")
    if session_id == auth.session_id:
        sessions.clear_cookies(response, settings)
    response.status_code = 204
    return response


@router.post("/api/v1/auth/sessions/revoke-others")
def revoke_other_sessions(auth: Auth, db: DbSession) -> dict[str, int]:
    return {"revoked": sessions.revoke_all(db, auth.user.id, except_session=auth.session_id)}


class ChangePasswordBody(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


@router.post("/api/v1/auth/password/change", response_model=SignedIn)
def change_password(
    body: ChangePasswordBody,
    auth: Auth,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
) -> SignedIn:
    """Every other session ends, and this one is replaced by a new one."""
    _limit(db, rate_limit.PASSWORD_CHANGES_PER_USER, auth.user.id)
    if not verify_password(repo.user_password_hash(db, auth.user.id), body.current_password):
        raise _error(400, "wrong_password", "Your current password isn't right.")
    try:
        check_policy(body.new_password, email=auth.user.email)
    except PasswordPolicyError as e:
        raise _error(422, "weak_password", str(e)) from e
    if body.new_password == body.current_password:
        raise _error(422, "weak_password", "Choose a password you haven't used here just now.")
    user = repo.set_user_password(db, auth.user.id, hash_password(body.new_password), verify_email=False)
    assert user is not None
    sessions.revoke_all(db, user.id)
    _start_session(request, response, db, settings, user.id)
    background.add_task(_send_quietly, settings, mail.password_changed_mail(user.email, settings.public_app_url.rstrip("/")))
    _log.info("auth_password_changed", user_id=user.id)
    return SignedIn(user=_me(db, user))


class SessionState(BaseModel):
    user: MeResponse | None


@router.get("/api/v1/auth/session", response_model=SessionState)
def session_state(request: Request, db: DbSession, settings: AppSettings) -> SessionState:
    """Who is signed in, if anyone -- 200 either way, so a page open to
    everyone (the landing page, sign-in) can ask without an error."""
    ctx = authenticate(request, db, settings)
    return SessionState(user=_me(db, ctx.user) if ctx else None)


@router.get("/api/v1/me", response_model=MeResponse)
def get_me(current_user: CurrentUser, db: DbSession) -> MeResponse:
    return _me(db, current_user)


class MePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    default_provider: str | None = None


@router.patch("/api/v1/me", response_model=MeResponse)
def patch_me(body: MePatch, current_user: CurrentUser, db: DbSession) -> MeResponse:
    user = current_user
    if "name" in body.model_fields_set:
        name = " ".join((body.name or "").split())
        if not name:
            raise _error(422, "invalid_name", "Enter your name.")
        updated = repo.set_user_name(db, current_user.id, name)
        assert updated is not None
        user = updated
    if "default_provider" in body.model_fields_set:
        provider: LlmProvider | None = None
        if body.default_provider is not None:
            try:
                provider = LlmProvider(body.default_provider)
            except ValueError as e:
                raise _error(400, "unsupported_provider", f"unknown provider '{body.default_provider}'") from e
            if not any(k.provider == provider for k in repo.list_api_keys(db, current_user.id)):
                raise _error(422, "no_key_for_provider", f"save a {provider.value} key before making it the default")
        updated = repo.set_default_provider(db, current_user.id, provider)
        assert updated is not None  # the current user exists
        user = updated
    return _me(db, user)
