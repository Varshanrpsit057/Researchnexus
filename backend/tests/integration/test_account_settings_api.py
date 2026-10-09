"""Account + provider settings (Phase 14): the default provider a user picks,
the provider actually in use, re-checking a stored key, and service health."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_session_factory
from app.domain.user import LlmCapabilities, LlmProvider, LlmTestResult
from app.llm.session import resolve_llm_session
from app.main import create_app
from tests.auth_helpers import sign_in

SECRET_KEY = "sk-live-abcdefghijklmnop-9z8y"


def _client(tmp_path: Path) -> tuple[TestClient, Settings]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
        key_vault_secret=Fernet.generate_key().decode(),
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), settings


def _token(c: TestClient) -> str:
    return sign_in(c, "r@example.com")


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def _probe_answers(monkeypatch: pytest.MonkeyPatch, working: set[str]) -> list[str]:
    """Keys whose provider is in `working` pass the probe; records the keys it saw."""
    import app.routers.settings_keys as sk

    seen: list[str] = []

    async def _probe(provider: LlmProvider, api_key: str, *, transport: object = None) -> LlmTestResult:
        seen.append(api_key)
        if provider.value in working:
            return LlmTestResult(success=True, latency_ms=12, capabilities=LlmCapabilities(json_mode=True, context_tokens=131072, streaming=True))
        return LlmTestResult(success=False, message="invalid api key")

    monkeypatch.setattr(sk, "probe", _probe)
    return seen


def _save(c: TestClient, token: str, provider: str, key: str = SECRET_KEY) -> dict:
    r = c.put("/api/v1/settings/llm-keys", json={"provider": provider, "api_key": key}, headers=_h(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_the_default_provider_is_stored_and_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, settings = _client(tmp_path)
    token = _token(c)
    _probe_answers(monkeypatch, {"groq", "openai"})
    _save(c, token, "groq")
    _save(c, token, "openai")

    me = c.get("/api/v1/me", headers=_h(token)).json()
    assert me["default_provider"] is None
    assert me["active_provider"] == "groq"  # no preference: the first key saved that works

    r = c.patch("/api/v1/me", json={"default_provider": "openai"}, headers=_h(token))
    assert r.status_code == 200, r.text
    assert (r.json()["default_provider"], r.json()["active_provider"]) == ("openai", "openai")

    db = get_session_factory()()
    try:
        user = repo.get_user(db, me["id"])
        assert user is not None
        session = resolve_llm_session(db, user, settings)
        assert session is not None and session.provider is LlmProvider.OPENAI  # every LLM stage uses it
    finally:
        db.close()

    cleared = c.patch("/api/v1/me", json={"default_provider": None}, headers=_h(token)).json()
    assert (cleared["default_provider"], cleared["active_provider"]) == (None, "groq")


def test_a_default_needs_a_saved_key_and_a_known_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = _client(tmp_path)
    token = _token(c)
    _probe_answers(monkeypatch, {"groq"})
    _save(c, token, "groq")
    r = c.patch("/api/v1/me", json={"default_provider": "gemini"}, headers=_h(token))
    assert r.status_code == 422 and r.json()["detail"]["error"]["code"] == "no_key_for_provider"
    r = c.patch("/api/v1/me", json={"default_provider": "not-a-provider"}, headers=_h(token))
    assert r.status_code == 400 and r.json()["detail"]["error"]["code"] == "unsupported_provider"
    assert c.patch("/api/v1/me", json={"default_provider": "groq"}).status_code == 401


def test_a_failing_default_falls_back_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = _client(tmp_path)
    token = _token(c)
    _probe_answers(monkeypatch, {"groq"})
    _save(c, token, "groq")
    _save(c, token, "openai")  # its probe fails: stored as failed
    c.patch("/api/v1/me", json={"default_provider": "openai"}, headers=_h(token))
    me = c.get("/api/v1/me", headers=_h(token)).json()
    assert (me["default_provider"], me["active_provider"], me["has_working_llm_key"]) == ("openai", "groq", True)


def test_removing_the_default_key_clears_the_preference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = _client(tmp_path)
    token = _token(c)
    _probe_answers(monkeypatch, {"groq", "openai"})
    _save(c, token, "groq")
    _save(c, token, "openai")
    c.patch("/api/v1/me", json={"default_provider": "openai"}, headers=_h(token))
    assert c.delete("/api/v1/settings/llm-keys/openai", headers=_h(token)).status_code == 204
    me = c.get("/api/v1/me", headers=_h(token)).json()
    assert (me["default_provider"], me["active_provider"]) == (None, "groq")


def test_a_stored_key_can_be_checked_again_without_sending_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = _client(tmp_path)
    token = _token(c)
    seen = _probe_answers(monkeypatch, {"groq"})
    saved = _save(c, token, "groq")
    assert saved["status"] == "working"

    # the provider revokes the key: checking again (no key in the request) records that
    _probe_answers(monkeypatch, set())
    r = c.post("/api/v1/settings/llm-keys/groq/check", headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"]["status"] == "failed" and body["key"]["key_last4"] == "9z8y"
    assert body["result"] == {"success": False, "message": "invalid api key"}
    assert body["key"]["checked_at"].endswith(("Z", "+00:00"))
    assert SECRET_KEY not in r.text and seen == [SECRET_KEY]
    assert c.get("/api/v1/me", headers=_h(token)).json()["has_working_llm_key"] is False

    assert c.post("/api/v1/settings/llm-keys/gemini/check", headers=_h(token)).status_code == 404
    assert c.post("/api/v1/settings/llm-keys/nope/check", headers=_h(token)).status_code == 400


def test_keys_list_in_the_order_they_were_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = _client(tmp_path)
    token = _token(c)
    _probe_answers(monkeypatch, {"groq", "openai", "gemini"})
    for p in ("openai", "gemini", "groq"):
        _save(c, token, p)
    keys = c.get("/api/v1/settings/llm-keys", headers=_h(token)).json()["keys"]
    assert [k["provider"] for k in keys] == ["openai", "gemini", "groq"]
    assert all(k["checked_at"].endswith(("Z", "+00:00")) for k in keys)


def test_account_times_read_back_as_utc(tmp_path: Path) -> None:
    c, _ = _client(tmp_path)
    token = _token(c)
    assert c.get("/api/v1/me", headers=_h(token)).json()["created_at"].endswith(("Z", "+00:00"))


def test_health_reports_its_checks(tmp_path: Path) -> None:
    c, _ = _client(tmp_path)
    body = c.get("/health").json()
    assert body["status"] == "ok"
    assert body["checks"] == {"db": "ok"}
    assert isinstance(body["version"], str) and body["version"]
