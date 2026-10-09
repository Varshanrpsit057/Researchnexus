"""Signing in for tests that are about something else.

`sign_in` gives a test a session token for an email -- the account is made
(verified, as a finished sign-up would leave it) when it doesn't exist yet
-- straight through the same repository and session code the real flow
ends in, so tests that aren't about signing in don't each walk the emailed
code flow (or run into its rate limits). The flow itself is tested end to
end in tests/integration/test_auth_api.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import repository as repo
from app.db.session import get_session_factory
from app.jobs.runner import new_id
from app.security import sessions

TEST_PASSWORD = "correct-horse-42"
# headers for a request made signed out, from a client that otherwise sends a session
ANONYMOUS = {"Authorization": ""}


def sign_in(client: TestClient, email: str = "r@example.com", *, name: str | None = None) -> str:
    settings = client.app.state.settings  # type: ignore[attr-defined]
    db = get_session_factory()()
    try:
        user = repo.find_user_for_sign_in(db, email)
        if user is None:
            from app.security.passwords import hash_password

            user = repo.create_user(
                db,
                user_id=new_id("usr"),
                email=email.strip().lower(),
                name=name,
                password_hash=hash_password(TEST_PASSWORD),
                email_verified_at=datetime.now(timezone.utc),
            )
        return sessions.create(db, settings, user.id, user_agent="pytest", ip="testclient")
    finally:
        db.close()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def signed_in(client: TestClient, email: str = "r@example.com") -> TestClient:
    """The client, sending `email`'s session with every request that
    doesn't name another (an explicit Authorization header still wins)."""
    client.headers.update(bearer(sign_in(client, email)))
    return client
