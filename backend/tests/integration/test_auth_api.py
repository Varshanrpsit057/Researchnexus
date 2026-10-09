"""Sign-up, sign-in with an emailed code, password reset and sessions, end
to end through the API (app/routers/auth.py) with the in-memory mailer."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.models import AuthChallengeORM, AuthSessionORM, UserORM
from app.db.session import get_session_factory
from app.main import create_app
from app.services import mail
from tests.auth_helpers import ANONYMOUS

PASSWORD = "Tidal-pools-9"


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    kwargs: dict[str, object] = {
        "data_dir": tmp_path,
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "secret_key": "s" * 40,
        "key_vault_secret": Fernet.generate_key().decode(),
        "environment": "test",
    }
    kwargs.update(overrides)
    settings = Settings(_env_file=None, **kwargs)  # type: ignore[call-arg, arg-type]
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _last_code(email: str) -> str:
    messages = mail.outbox.for_address(email)
    assert messages, f"no email to {email}"
    found = re.search(r"\b(\d{6})\b", messages[0].text)
    assert found, messages[0].text
    return found.group(1)


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("rn_csrf") or ""}


def _db():
    return get_session_factory()()


def _sign_up(client: TestClient, email: str = "ada@example.org", name: str = "Ada Lovelace") -> dict:
    started = client.post("/api/v1/auth/signup", json={"name": name, "email": email, "password": PASSWORD})
    assert started.status_code == 202, started.text
    done = client.post("/api/v1/auth/verify", json={"challenge_id": started.json()["challenge_id"], "code": _last_code(email)})
    assert done.status_code == 200, done.text
    return done.json()["user"]


def _log_in(client: TestClient, email: str = "ada@example.org", password: str = PASSWORD) -> dict:
    started = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert started.status_code == 200, started.text
    done = client.post("/api/v1/auth/verify", json={"challenge_id": started.json()["challenge_id"], "code": _last_code(email)})
    assert done.status_code == 200, done.text
    return done.json()["user"]


# --- sign up -------------------------------------------------------------------


def test_sign_up_emails_a_code_and_only_the_code_makes_the_account_and_session(tmp_path: Path) -> None:
    client = _client(tmp_path)
    started = client.post("/api/v1/auth/signup", json={"name": "  Ada   Lovelace ", "email": "Ada@Example.org", "password": PASSWORD})
    assert started.status_code == 202
    body = started.json()
    assert body["purpose"] == "signup" and body["destination"].endswith("@example.org") and "ada" not in body["destination"]
    assert 0 < body["expires_in"] <= 300 and body["resend_in"] > 0
    # nothing is signed in, and no account exists, until the code comes back
    assert "rn_session" not in client.cookies
    assert client.get("/api/v1/me").status_code == 401
    with _db() as db:
        assert repo.find_user_for_sign_in(db, "ada@example.org") is None

    sent = mail.outbox.for_address("ada@example.org")
    assert len(sent) == 1 and sent[0].purpose == "signup" and "Ada Lovelace" in sent[0].text
    done = client.post("/api/v1/auth/verify", json={"challenge_id": body["challenge_id"], "code": _last_code("ada@example.org")})
    assert done.status_code == 200
    user = done.json()["user"]
    assert user["email"] == "ada@example.org" and user["name"] == "Ada Lovelace"
    assert user["email_verified"] is True and user["has_password"] is True
    assert "token" not in done.text  # the session is a cookie, never in a reply
    cookie = done.headers.get_list("set-cookie")
    assert any(c.startswith("rn_session=") and "HttpOnly" in c and "SameSite=lax" in c for c in cookie)
    assert any(c.startswith("rn_csrf=") and "HttpOnly" not in c for c in cookie)
    assert client.get("/api/v1/me").json()["id"] == user["id"]


def test_the_session_state_says_who_is_signed_in_without_an_error_for_nobody(tmp_path: Path) -> None:
    client = _client(tmp_path)
    nobody = client.get("/api/v1/auth/session")
    assert nobody.status_code == 200 and nobody.json() == {"user": None}
    user = _sign_up(client)
    assert client.get("/api/v1/auth/session").json()["user"]["id"] == user["id"]


def test_the_code_is_six_random_digits_and_only_its_hmac_is_stored(tmp_path: Path) -> None:
    client = _client(tmp_path)
    challenge = client.post("/api/v1/auth/signup", json={"name": "Ada", "email": "ada@example.org", "password": PASSWORD}).json()
    code = _last_code("ada@example.org")
    assert re.fullmatch(r"\d{6}", code)
    with _db() as db:
        row = db.get(AuthChallengeORM, challenge["challenge_id"])
        assert row is not None and code not in row.code_hash and len(row.code_hash) == 64
        assert row.payload["password_hash"].startswith("$argon2id$") and PASSWORD not in str(row.payload)


def test_signing_up_with_a_taken_email_answers_the_same_and_tells_the_owner_instead(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    client.cookies.clear()
    mail.outbox.clear()
    again = client.post("/api/v1/auth/signup", json={"name": "Mallory", "email": "ADA@example.org", "password": "Other-pass-77"})
    assert again.status_code == 202
    assert set(again.json()) == {"challenge_id", "purpose", "destination", "expires_in", "resend_in", "resends_left"}
    sent = mail.outbox.for_address("ada@example.org")
    assert len(sent) == 1 and sent[0].purpose == "signup-existing"
    assert not re.search(r"\b\d{6}\b", sent[0].text)  # no code to enter
    # no code can finish it
    for guess in ("000000", "123456"):
        wrong = client.post("/api/v1/auth/verify", json={"challenge_id": again.json()["challenge_id"], "code": guess})
        assert wrong.status_code == 400 and wrong.json()["detail"]["error"]["code"] == "code_wrong"
    with _db() as db:
        assert db.execute(select(UserORM)).scalars().all().__len__() == 1


@pytest.mark.parametrize(
    ("password", "why"),
    [("short1!", "at least 10"), ("onlyletters", "number or symbol"), ("1234567890", "number or symbol"), ("password123", "too common"), ("ada-lovelace-99", "email")],
)
def test_sign_up_refuses_a_weak_password_and_says_why(tmp_path: Path, password: str, why: str) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/v1/auth/signup", json={"name": "Ada", "email": "ada-lovelace@example.org", "password": password})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"]["code"] == "weak_password" and why in resp.json()["detail"]["error"]["message"]
    assert mail.outbox.all() == []


def test_sign_up_needs_a_name_and_a_real_email(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for email in ["", "   ", "not-an-email", "a@b", "a b@c.org"]:
        resp = client.post("/api/v1/auth/signup", json={"name": "Ada", "email": email, "password": PASSWORD})
        assert resp.status_code == 422, email
    assert client.post("/api/v1/auth/signup", json={"name": "   ", "email": "a@b.org", "password": PASSWORD}).status_code == 422


# --- sign in -------------------------------------------------------------------


def test_sign_in_needs_the_right_password_then_the_emailed_code(tmp_path: Path) -> None:
    client = _client(tmp_path)
    user = _sign_up(client)
    client.cookies.clear()

    wrong = client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": "Wrong-pass-11"})
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@example.org", "password": PASSWORD})
    for resp in (wrong, unknown):
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"]["code"] == "invalid_credentials"
    # the same answer either way: it never says which emails have accounts
    assert wrong.json() == unknown.json()

    mail.outbox.clear()
    started = client.post("/api/v1/auth/login", json={"email": "  ADA@example.org", "password": PASSWORD})
    assert started.status_code == 200 and started.json()["purpose"] == "login"
    assert "rn_session" not in client.cookies
    assert client.get("/api/v1/me").status_code == 401  # the password alone signs no one in
    done = client.post("/api/v1/auth/verify", json={"challenge_id": started.json()["challenge_id"], "code": _last_code("ada@example.org")})
    assert done.status_code == 200 and done.json()["user"]["id"] == user["id"]
    assert client.get("/api/v1/me").status_code == 200


def test_a_code_works_once(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    started = client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).json()
    code = _last_code("ada@example.org")
    assert client.post("/api/v1/auth/verify", json={"challenge_id": started["challenge_id"], "code": code}).status_code == 200
    replay = client.post("/api/v1/auth/verify", json={"challenge_id": started["challenge_id"], "code": code})
    assert replay.status_code == 400 and replay.json()["detail"]["error"]["code"] == "code_used"


def test_a_code_expires(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    client.cookies.clear()
    started = client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).json()
    code = _last_code("ada@example.org")
    with _db() as db:
        row = db.get(AuthChallengeORM, started["challenge_id"])
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    late = client.post("/api/v1/auth/verify", json={"challenge_id": started["challenge_id"], "code": code})
    assert late.status_code == 400 and late.json()["detail"]["error"]["code"] == "code_expired"
    assert client.get("/api/v1/me").status_code == 401


def test_too_many_wrong_codes_close_the_challenge_even_to_the_right_code(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    client.cookies.clear()
    started = client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).json()
    code = _last_code("ada@example.org")
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    answers = [client.post("/api/v1/auth/verify", json={"challenge_id": started["challenge_id"], "code": wrong}).json() for _ in range(5)]
    assert [a["detail"]["error"]["code"] for a in answers] == ["code_wrong"] * 4 + ["code_locked"]
    assert "4 tries left" in answers[0]["detail"]["error"]["message"]
    right = client.post("/api/v1/auth/verify", json={"challenge_id": started["challenge_id"], "code": code})
    assert right.status_code == 400 and right.json()["detail"]["error"]["code"] == "code_locked"
    assert client.get("/api/v1/me").status_code == 401


def test_a_new_code_waits_for_the_cooldown_replaces_the_old_one_and_runs_out(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    client.cookies.clear()
    started = client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).json()
    first = _last_code("ada@example.org")
    too_soon = client.post("/api/v1/auth/resend", json={"challenge_id": started["challenge_id"]})
    assert too_soon.status_code == 429 and too_soon.json()["detail"]["error"]["code"] == "resend_too_soon"

    def cool_down() -> None:
        with _db() as db:
            row = db.get(AuthChallengeORM, started["challenge_id"])
            assert row is not None
            row.last_sent_at = datetime.now(timezone.utc) - timedelta(minutes=2)
            db.commit()

    codes = []
    for _ in range(3):
        cool_down()
        resent = client.post("/api/v1/auth/resend", json={"challenge_id": started["challenge_id"]})
        assert resent.status_code == 200
        codes.append(_last_code("ada@example.org"))
    assert resent.json()["resends_left"] == 0
    cool_down()
    spent = client.post("/api/v1/auth/resend", json={"challenge_id": started["challenge_id"]})
    assert spent.status_code == 400 and spent.json()["detail"]["error"]["code"] == "resend_limit"
    if first != codes[-1]:  # the old code stopped working (unless the draw repeated it)
        old = client.post("/api/v1/auth/verify", json={"challenge_id": started["challenge_id"], "code": first})
        assert old.json()["detail"]["error"]["code"] == "code_wrong"
    ok = client.post("/api/v1/auth/verify", json={"challenge_id": started["challenge_id"], "code": codes[-1]})
    assert ok.status_code == 200


def test_repeated_wrong_passwords_are_rate_limited(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    client.cookies.clear()
    statuses = [client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": f"Wrong-pass-{i}"}).status_code for i in range(11)]
    assert statuses[:10] == [401] * 10 and statuses[10] == 429
    blocked = client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": PASSWORD})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    assert blocked.json()["detail"]["error"]["code"] == "rate_limited"


def test_codes_to_one_email_are_rate_limited_against_email_bombing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)  # one code sent
    statuses = [client.post("/api/v1/auth/password/forgot", json={"email": "ada@example.org"}).status_code for _ in range(8)]
    assert statuses[:7] == [202] * 7 and statuses[7] == 429
    assert len(mail.outbox.for_address("ada@example.org")) == 8  # 1 sign-up + 7 resets, then no more


def test_a_code_for_one_purpose_cannot_finish_another(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    client.cookies.clear()
    reset = client.post("/api/v1/auth/password/forgot", json={"email": "ada@example.org"}).json()
    as_login = client.post("/api/v1/auth/verify", json={"challenge_id": reset["challenge_id"], "code": _last_code("ada@example.org")})
    assert as_login.status_code == 400 and client.get("/api/v1/me").status_code == 401
    login = client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).json()
    as_reset = client.post(
        "/api/v1/auth/password/reset",
        json={"challenge_id": login["challenge_id"], "code": _last_code("ada@example.org"), "password": "Brand-new-pass-1"},
    )
    assert as_reset.status_code == 400 and client.get("/api/v1/me").status_code == 401
    assert client.post("/api/v1/auth/verify", json={"challenge_id": "chl_made_up", "code": "123456"}).status_code == 400


# --- sessions ------------------------------------------------------------------


def test_signing_in_replaces_any_session_the_browser_already_had(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    planted = client.cookies.get("rn_session")
    _log_in(client)
    fresh = client.cookies.get("rn_session")
    assert fresh and fresh != planted
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {planted}"}).status_code == 401


def test_sign_out_ends_the_session(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    token = client.cookies.get("rn_session")
    out = client.post("/api/v1/auth/logout", headers=_csrf(client))
    assert out.status_code == 204
    assert any(c.startswith("rn_session=") and "Max-Age=0" in c for c in out.headers.get_list("set-cookie"))
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_session_ends_when_it_expires_or_sits_unused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    assert client.get("/api/v1/me").status_code == 200
    with _db() as db:
        row = db.execute(select(AuthSessionORM)).scalars().one()
        row.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=73)
        db.commit()
    assert client.get("/api/v1/me").status_code == 401  # idle for longer than 72 h

    _log_in(client)
    with _db() as db:
        row = db.execute(select(AuthSessionORM).where(AuthSessionORM.revoked_at.is_(None))).scalars().all()[-1]
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/me").status_code == 401


def test_a_cookie_session_needs_the_csrf_token_to_change_anything(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    refused = client.patch("/api/v1/me", json={"name": "Ada L."})
    assert refused.status_code == 403 and refused.json()["detail"]["error"]["code"] == "csrf_failed"
    forged = client.patch("/api/v1/me", json={"name": "Ada L."}, headers={"X-CSRF-Token": "0" * 64})
    assert forged.status_code == 403
    ok = client.patch("/api/v1/me", json={"name": "Ada L."}, headers=_csrf(client))
    assert ok.status_code == 200 and ok.json()["name"] == "Ada L."
    # reading needs no token; a bearer session (never sent by a browser on its own) needs none either
    assert client.get("/api/v1/me").status_code == 200
    token = client.cookies.get("rn_session")
    client.cookies.clear()
    assert client.patch("/api/v1/me", json={"name": "Ada"}, headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_state_changing_requests_from_another_site_are_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    evil = client.post("/api/v1/auth/login", json={"email": "a@b.org", "password": PASSWORD}, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403 and evil.json()["detail"]["error"]["code"] == "bad_origin"
    ours = client.post("/api/v1/auth/login", json={"email": "a@b.org", "password": PASSWORD}, headers={"Origin": "http://localhost:3000"})
    assert ours.status_code == 401


def test_sessions_are_listed_and_revoked_and_other_devices_signed_out(tmp_path: Path) -> None:
    laptop = _client(tmp_path)
    _sign_up(laptop)
    phone = TestClient(laptop.app)
    _log_in(phone)
    listed = laptop.get("/api/v1/auth/sessions").json()["sessions"]
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1
    other = next(s for s in listed if not s["current"])
    assert laptop.delete(f"/api/v1/auth/sessions/{other['id']}", headers=_csrf(laptop)).status_code == 204
    assert phone.get("/api/v1/me").status_code == 401
    _log_in(phone)
    revoked = laptop.post("/api/v1/auth/sessions/revoke-others", headers=_csrf(laptop)).json()
    assert revoked == {"revoked": 1} and phone.get("/api/v1/me").status_code == 401
    assert laptop.get("/api/v1/me").status_code == 200


# --- passwords -------------------------------------------------------------------


def test_a_forgotten_password_is_reset_by_emailed_code_and_ends_every_other_session(tmp_path: Path) -> None:
    client = _client(tmp_path)
    user = _sign_up(client)
    elsewhere = client.cookies.get("rn_session")
    client.cookies.clear()
    mail.outbox.clear()
    started = client.post("/api/v1/auth/password/forgot", json={"email": "ada@example.org"})
    assert started.status_code == 202 and started.json()["purpose"] == "reset"
    code = _last_code("ada@example.org")
    weak = client.post("/api/v1/auth/password/reset", json={"challenge_id": started.json()["challenge_id"], "code": code, "password": "weak"})
    assert weak.status_code == 422  # and the code is still good
    done = client.post("/api/v1/auth/password/reset", json={"challenge_id": started.json()["challenge_id"], "code": code, "password": "New-tide-pool-3"})
    assert done.status_code == 200 and done.json()["user"]["id"] == user["id"]
    assert client.get("/api/v1/me").status_code == 200
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {elsewhere}"}).status_code == 401
    assert any(m.purpose == "password-changed" for m in mail.outbox.for_address("ada@example.org"))
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": "New-tide-pool-3"}).status_code == 200


def test_a_reset_for_an_unknown_email_answers_the_same_and_sends_nothing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.org"})
    assert resp.status_code == 202 and resp.json()["purpose"] == "reset"
    assert mail.outbox.all() == []
    guess = client.post("/api/v1/auth/password/reset", json={"challenge_id": resp.json()["challenge_id"], "code": "123456", "password": "New-tide-pool-3"})
    assert guess.status_code == 400 and guess.json()["detail"]["error"]["code"] == "code_wrong"


def test_an_account_from_before_passwords_claims_one_through_reset_and_keeps_its_data(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with _db() as db:
        old = repo.create_user(db, user_id="usr_from_before", email="Grace@Example.org")  # no password, unverified
    cant = client.post("/api/v1/auth/login", json={"email": "grace@example.org", "password": "anything-at-all-1"})
    assert cant.status_code == 401 and "Forgot password" in cant.json()["detail"]["error"]["message"]
    started = client.post("/api/v1/auth/password/forgot", json={"email": "grace@example.org"}).json()
    done = client.post(
        "/api/v1/auth/password/reset", json={"challenge_id": started["challenge_id"], "code": _last_code("Grace@Example.org"), "password": "Compiler-1952"}
    )
    assert done.status_code == 200
    me = done.json()["user"]
    assert me["id"] == old.id and me["has_password"] and me["email_verified"]


def test_changing_the_password_checks_the_current_one_and_signs_out_other_devices(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    other = TestClient(client.app)
    _log_in(other)
    wrong = client.post("/api/v1/auth/password/change", json={"current_password": "Nope-nope-11", "new_password": "Another-pass-5"}, headers=_csrf(client))
    assert wrong.status_code == 400 and wrong.json()["detail"]["error"]["code"] == "wrong_password"
    before = client.cookies.get("rn_session")
    ok = client.post("/api/v1/auth/password/change", json={"current_password": PASSWORD, "new_password": "Another-pass-5"}, headers=_csrf(client))
    assert ok.status_code == 200
    assert client.cookies.get("rn_session") != before and client.get("/api/v1/me").status_code == 200
    assert other.get("/api/v1/me").status_code == 401


# --- what needs signing in ---------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/papers"),
        ("GET", "/api/v1/papers/pap_x"),
        ("GET", "/api/v1/papers/pap_x/profile"),
        ("POST", "/api/v1/papers/upload"),
        ("GET", "/api/v1/jobs/job_x"),
        ("GET", "/api/v1/workspaces"),
        ("GET", "/api/v1/workspaces/ws_x"),
        ("GET", "/api/v1/usage"),
        ("GET", "/api/v1/settings/llm-keys"),
        ("GET", "/api/v1/auth/sessions"),
        ("POST", "/api/v1/auth/password/change"),
        ("GET", "/api/v1/service/sources"),
    ],
)
def test_protected_endpoints_refuse_requests_without_a_session(tmp_path: Path, method: str, path: str) -> None:
    client = _client(tmp_path)
    resp = client.request(method, path, headers=ANONYMOUS)
    assert resp.status_code == 401, (method, path, resp.status_code)


def test_one_readers_job_is_invisible_to_another(tmp_path: Path) -> None:
    from app.domain.jobs import Job, JobKind

    client = _client(tmp_path)
    owner = _sign_up(client, "owner@example.org")
    with _db() as db:
        repo.create_job(db, Job(job_id="job_private", owner_id=owner["id"], kind=JobKind.INGEST))
    assert client.get("/api/v1/jobs/job_private").status_code == 200
    stranger = TestClient(client.app)
    _sign_up(stranger, "stranger@example.org", "Stranger")
    assert stranger.get("/api/v1/jobs/job_private").status_code == 404


def test_codes_and_passwords_never_reach_the_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = _client(tmp_path)
    _sign_up(client)
    signup_code = _last_code("ada@example.org")
    client.cookies.clear()
    _log_in(client)
    login_code = _last_code("ada@example.org")
    client.post("/api/v1/auth/login", json={"email": "ada@example.org", "password": "Wrong-pass-11"})
    out = capsys.readouterr()
    logged = out.out + out.err
    assert "auth_login_failed" in logged  # the log is on
    for secret in (PASSWORD, "Wrong-pass-11", client.cookies.get("rn_session") or "x" * 40):
        assert secret not in logged
    for code in (signup_code, login_code):  # (not as a timestamp's microseconds)
        assert not re.search(rf"(?<![\d.]){code}(?!\d)", logged)


def test_sign_up_can_be_limited_to_some_email_domains(tmp_path: Path) -> None:
    client = _client(tmp_path, signup_allowed_domains=["university.edu"])
    outside = client.post("/api/v1/auth/signup", json={"name": "Ada", "email": "ada@gmail.com", "password": PASSWORD})
    assert outside.status_code == 403 and outside.json()["detail"]["error"]["code"] == "signup_restricted"
    assert mail.outbox.all() == []
    for email in ("ada@university.edu", "bob@cs.university.edu"):
        assert client.post("/api/v1/auth/signup", json={"name": "Ada", "email": email, "password": PASSWORD}).status_code == 202


def test_a_discovery_run_and_a_profile_edit_belong_to_their_owner(tmp_path: Path) -> None:
    from app.db.models import PaperORM, SearchRunORM
    from app.domain.profile import ProfileField, ResearchProfile
    from app.services.normalize.canonical import title_hash

    client = _client(tmp_path)
    owner = _sign_up(client, "owner@example.org")
    with _db() as db:
        repo.save_paper(db, PaperORM(id="pap_seed", title="Seed", title_hash=title_hash("Seed"), has_full_text=True))
        db.add(SearchRunORM(id="run_private", seed_paper_id="pap_seed", owner_id=owner["id"], started_at=datetime.now(timezone.utc)))
        db.commit()
        profile = ResearchProfile(profile_id="prof_1", paper_id="pap_seed", title="Seed", abstract="ab", domain=ProfileField(value="IR"), research_problem=ProfileField(value="retrieval"))
        repo.upsert_profile(db, profile, owner_id=owner["id"])
    stranger = TestClient(client.app)
    _sign_up(stranger, "stranger@example.org", "Stranger")
    assert stranger.get("/api/v1/papers/pap_seed/related", params={"run_id": "run_private"}).status_code == 404
    edit = stranger.patch("/api/v1/papers/pap_seed/profile", json={"research_problem": "vandalised"}, headers=_csrf(stranger))
    assert edit.status_code == 403 and edit.json()["detail"]["error"]["code"] == "not_profile_owner"
