from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from app.config import Settings, get_settings
from app.main import create_app


def _make_client(tmp_path: Path, **overrides: object) -> TestClient:
    db_path = tmp_path / "test.db"
    kwargs: dict[str, object] = {
        "data_dir": tmp_path,
        "database_url": f"sqlite:///{db_path}",
        "jwt_secret": "test-jwt-secret",
        "key_vault_secret": Fernet.generate_key().decode(),
    }
    kwargs.update(overrides)
    settings = Settings(_env_file=None, **kwargs)  # type: ignore[call-arg, arg-type]
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_create_session_then_get_me(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    session_resp = client.post(
        "/api/v1/auth/session", json={"email": "researcher@example.com", "password": "anything"}
    )
    assert session_resp.status_code == 200
    body = session_resp.json()
    assert "token" in body and "expires_at" in body

    me_resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me_resp.status_code == 200
    me = me_resp.json()
    assert me["email"] == "researcher@example.com"
    assert me["has_working_llm_key"] is False


def test_get_me_without_token_is_401(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"]["code"] == "unauthenticated"


def test_get_me_with_garbage_token_is_401(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"]["code"] == "unauthenticated"


def test_repeat_session_for_same_email_reuses_the_same_user(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    first = client.post("/api/v1/auth/session", json={"email": "a@example.com", "password": "x"}).json()
    second = client.post("/api/v1/auth/session", json={"email": "a@example.com", "password": "y"}).json()
    first_sub = jose_jwt.get_unverified_claims(first["token"])["sub"]
    second_sub = jose_jwt.get_unverified_claims(second["token"])["sub"]
    assert first_sub == second_sub
