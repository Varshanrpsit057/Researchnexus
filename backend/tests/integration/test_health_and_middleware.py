"""Health endpoints and the request middleware (app/routers/health.py,
app/middleware.py), and what a production server does and doesn't expose."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from tests.auth_helpers import signed_in


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
    return TestClient(app, raise_server_exceptions=False)


def test_liveness_answers_without_touching_the_database(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/health/live").json() == {"status": "ok"}


def test_readiness_checks_the_database_schema_and_storage(tmp_path: Path) -> None:
    client = _client(tmp_path)
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "schema": "ok", "storage": "ok"}
    assert client.get("/health").json()["checks"] == {"db": "ok"}  # the original summary still answers


@pytest.mark.skipif(os.environ.get("RESEARCHNEXUS_TEST_ON_POSTGRES") == "1", reason="the PostgreSQL test databases are migrated")
def test_readiness_is_503_until_a_deployed_database_is_migrated(tmp_path: Path) -> None:
    # a deployed server doesn't create tables itself: an unmigrated database isn't ready
    client = _client(tmp_path, db_auto_create=False)
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"]["schema"] == "migration_pending"
    assert client.get("/health/live").status_code == 200  # but the process is alive


def test_providers_report_their_setup_and_never_a_key(tmp_path: Path) -> None:
    client = _client(tmp_path, openalex_api_key="secret-openalex-key-value")
    body = client.get("/health/providers")
    assert body.status_code == 200 and body.json()["status"] == "ok"
    assert "secret-openalex-key-value" not in body.text
    assert body.json()["email"] == {"backend": "memory", "configured": True}


def test_every_response_has_a_request_id_and_security_headers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/health/live")
    assert len(resp.headers["x-request-id"]) == 32
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    # a caller's own request id is kept, a malformed one replaced
    assert client.get("/health/live", headers={"X-Request-ID": "trace-abc-12345"}).headers["x-request-id"] == "trace-abc-12345"
    assert client.get("/health/live", headers={"X-Request-ID": "bad id\n"}).headers["x-request-id"] != "bad id\n"
    auth = client.post("/api/v1/auth/login", json={"email": "a@b.org", "password": "x"})
    assert auth.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in resp.headers  # plain http in tests


def test_an_unexpected_error_is_a_json_500_naming_the_request(tmp_path: Path) -> None:
    client = _client(tmp_path)
    boom = APIRouter()

    @boom.get("/api/v1/boom")
    def explode() -> None:
        raise RuntimeError("database password is hunter2")

    client.app.include_router(boom)  # type: ignore[attr-defined]
    resp = client.get("/api/v1/boom")
    assert resp.status_code == 500
    error = resp.json()["detail"]["error"]
    assert error["code"] == "internal_error" and error["request_id"] == resp.headers["x-request-id"]
    assert "hunter2" not in resp.text


def test_request_bodies_are_capped(tmp_path: Path) -> None:
    client = signed_in(_client(tmp_path, max_pdf_mb=1, max_json_body_kb=4))
    big_json = client.post("/api/v1/auth/login", content=b'{"email": "' + b"a" * 8000 + b'"}', headers={"Content-Type": "application/json"})
    assert big_json.status_code == 413 and big_json.json()["detail"]["error"]["code"] == "file_too_large"
    big_pdf = client.post("/api/v1/papers/upload", files={"file": ("big.pdf", b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024), "application/pdf")})
    assert big_pdf.status_code == 413

    def chunks():  # a body with no declared length is counted as it arrives
        for _ in range(4):
            yield b"x" * 2048

    streamed = client.post("/api/v1/auth/login", content=chunks(), headers={"Content-Type": "application/json"})
    assert streamed.status_code == 413


def test_production_hides_the_api_docs_and_the_dev_mailbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # built on SQLite here, which startup checks would refuse for real
    monkeypatch.setattr("app.main.enforce_config", lambda _settings: [])
    production = _client(
        tmp_path,
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'p.db'}",
        public_app_url="https://rn.example.org",
        cors_allowed_origins=["https://rn.example.org"],
        smtp_host="smtp.example.org",
        email_from="no-reply@example.org",
        db_auto_create=True,
    )
    assert production.get("/docs").status_code == 404
    assert production.get("/openapi.json").status_code == 404
    assert production.get("/api/v1/dev/mailbox", params={"email": "a@b.org"}).status_code == 404
    assert production.get("/health/live").headers["strict-transport-security"].startswith("max-age=")
    (tmp_path / "dev").mkdir()
    development = _client(tmp_path / "dev", environment="development")
    assert development.get("/docs").status_code == 200
    assert development.get("/api/v1/dev/mailbox", params={"email": "a@b.org"}).json() == {"messages": []}
