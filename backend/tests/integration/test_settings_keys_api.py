from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.domain.user import LlmCapabilities, LlmTestResult
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


def _authed_client(tmp_path: Path) -> tuple[TestClient, str]:
    client = _make_client(tmp_path)
    token = client.post("/api/v1/auth/session", json={"email": "r@example.com", "password": "x"}).json()["token"]
    return client, token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _patch_probe_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.routers.settings_keys as settings_keys_module

    async def _fake_probe(provider: object, api_key: str, *, transport: object = None) -> LlmTestResult:
        return LlmTestResult(
            success=True, latency_ms=1, capabilities=LlmCapabilities(json_mode=True, context_tokens=8192, streaming=True)
        )

    monkeypatch.setattr(settings_keys_module, "probe", _fake_probe)


def _patch_probe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.routers.settings_keys as settings_keys_module

    async def _fake_probe(provider: object, api_key: str, *, transport: object = None) -> LlmTestResult:
        return LlmTestResult(success=False, message="invalid api key")

    monkeypatch.setattr(settings_keys_module, "probe", _fake_probe)


def test_settings_keys_routes_require_auth(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get("/api/v1/settings/llm-keys")
    assert resp.status_code == 401


def test_unsupported_provider_returns_400(tmp_path: Path) -> None:
    client, token = _authed_client(tmp_path)
    resp = client.put(
        "/api/v1/settings/llm-keys",
        json={"provider": "not-a-real-provider", "api_key": "sk-x"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "unsupported_provider"


def test_put_key_stores_ciphertext_only_and_never_echoes_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_probe_success(monkeypatch)
    client, token = _authed_client(tmp_path)

    resp = client.put(
        "/api/v1/settings/llm-keys",
        json={"provider": "groq", "api_key": "sk-super-secret-plaintext-value"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "working"
    assert body["key_last4"] == "alue"
    assert "sk-super-secret-plaintext-value" not in resp.text

    list_resp = client.get("/api/v1/settings/llm-keys", headers=_auth_headers(token))
    assert list_resp.status_code == 200
    keys = list_resp.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["provider"] == "groq"
    assert "key_ciphertext" not in keys[0]
    assert "sk-super-secret-plaintext-value" not in list_resp.text


def test_put_key_with_failed_probe_stores_status_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe_failure(monkeypatch)
    client, token = _authed_client(tmp_path)
    resp = client.put(
        "/api/v1/settings/llm-keys", json={"provider": "groq", "api_key": "sk-bad-key"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


def test_delete_key_removes_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe_success(monkeypatch)
    client, token = _authed_client(tmp_path)
    client.put("/api/v1/settings/llm-keys", json={"provider": "groq", "api_key": "sk-abc12345"}, headers=_auth_headers(token))

    del_resp = client.delete("/api/v1/settings/llm-keys/groq", headers=_auth_headers(token))
    assert del_resp.status_code == 204

    list_resp = client.get("/api/v1/settings/llm-keys", headers=_auth_headers(token))
    assert list_resp.json()["keys"] == []


def test_test_endpoint_does_not_persist_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe_success(monkeypatch)
    client, token = _authed_client(tmp_path)

    resp = client.post(
        "/api/v1/settings/llm-keys/test",
        json={"provider": "groq", "api_key": "sk-not-persisted"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    list_resp = client.get("/api/v1/settings/llm-keys", headers=_auth_headers(token))
    assert list_resp.json()["keys"] == []
