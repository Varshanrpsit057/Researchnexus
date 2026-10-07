from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.domain.user import LlmCapabilities, LlmTestResult
from app.main import create_app

_VALID_EXTRACTION_JSON = json.dumps(
    {
        "domain": {"value": "Retrieval-Augmented Generation", "quote": None},
        "subdomains": {"items": []},
        "research_problem": {"value": "grounding LLM answers in evidence", "quote": None},
        "research_questions": {"items": []},
        "objectives": {"items": []},
        "keywords": ["rag", "retrieval"],
        "methods": {"items": []},
        "models": {"items": []},
        "algorithms": {"items": []},
        "datasets": {"items": []},
        "evaluation_metrics": {"items": []},
        "findings": {"items": []},
        "limitations": {"items": []},
        "future_work": {"items": []},
        "important_entities": {"items": []},
        "cited_methods": {"items": []},
        "candidate_search_queries": ["retrieval augmented generation"],
    }
)


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
    token = client.post("/api/v1/auth/session", json={"email": "researcher@example.com", "password": "x"}).json()["token"]
    return client, token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upload_and_wait(client: TestClient, token: str, pdf_bytes: bytes) -> str:
    resp = client.post(
        "/api/v1/papers/upload",
        files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 202
    body = resp.json()
    paper_id = body["paper_id"]
    job_id = body["job"]["job_id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "partial"):
            assert job["status"] == "succeeded"
            break
        time.sleep(0.05)
    return paper_id


def _save_working_key(client: TestClient, token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.routers.settings_keys as settings_keys_module

    async def _fake_probe(provider: object, api_key: str, *, transport: object = None) -> LlmTestResult:
        return LlmTestResult(
            success=True, latency_ms=1, capabilities=LlmCapabilities(json_mode=True, context_tokens=8192, streaming=True)
        )

    monkeypatch.setattr(settings_keys_module, "probe", _fake_probe)
    resp = client.put(
        "/api/v1/settings/llm-keys", json={"provider": "groq", "api_key": "sk-test-key"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 200


def _mock_llm(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    import app.services.profile.pipeline as pipeline_module
    from app.domain.user import LlmProvider
    from app.llm.providers.openai_compat import OpenAiCompatClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    def fake_get_llm_client(provider: object) -> OpenAiCompatClient:
        return OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr(pipeline_module, "get_llm_client", fake_get_llm_client)


def test_analyze_without_a_working_key_returns_409(
    tmp_path: Path, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)

    resp = client.post(f"/api/v1/papers/{paper_id}/analyze", headers=_auth_headers(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "llm_key_required"


def test_analyze_requires_auth(tmp_path: Path, normal_paper_pdf_bytes: bytes) -> None:
    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)
    resp = client.post(f"/api/v1/papers/{paper_id}/analyze")
    assert resp.status_code == 401


def test_analyze_missing_paper_returns_404(tmp_path: Path) -> None:
    client, token = _authed_client(tmp_path)
    resp = client.post("/api/v1/papers/pap_does_not_exist/analyze", headers=_auth_headers(token))
    assert resp.status_code == 404


def test_analyze_succeeds_and_persists_provenance_checked_profile(
    tmp_path: Path, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)
    _save_working_key(client, token, monkeypatch)
    _mock_llm(monkeypatch, _VALID_EXTRACTION_JSON)

    resp = client.post(f"/api/v1/papers/{paper_id}/analyze", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"]["domain"]["value"] == "Retrieval-Augmented Generation"
    assert body["profile"]["keywords"] == ["rag", "retrieval"]
    assert body["warnings"] == []
    # no `quote` was given for domain -> unverified, never silently upgraded
    assert body["profile"]["domain"]["status"] == "unverified"

    # re-fetching via a second call (idempotent id) proves persistence, not
    # just an in-memory response
    second = client.post(f"/api/v1/papers/{paper_id}/analyze", headers=_auth_headers(token))
    assert second.json()["profile"]["profile_id"] == body["profile"]["profile_id"]

    # the analysed paper is in the reader's library, marked as analysed by them
    [entry] = [p for p in client.get("/api/v1/papers", headers=_auth_headers(token)).json()["papers"] if p["id"] == paper_id]
    assert entry["analyzed"] is True and "analyzed" in entry["roles"]


def test_analyze_with_malformed_llm_output_returns_degraded_profile_not_500(
    tmp_path: Path, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)
    _save_working_key(client, token, monkeypatch)
    _mock_llm(monkeypatch, "this is not valid json")

    resp = client.post(f"/api/v1/papers/{paper_id}/analyze", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["warnings"] == ["profile_extraction_failed"]
    assert body["extraction_confidence"] == "low"
    assert body["profile"]["domain"]["value"] == ""
    assert body["profile"]["title"]  # bibliographic fields still filled


def test_get_profile_before_analysis_returns_404(tmp_path: Path, normal_paper_pdf_bytes: bytes) -> None:
    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)
    resp = client.get(f"/api/v1/papers/{paper_id}/profile", headers=_auth_headers(token))
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"


def test_get_profile_missing_paper_returns_404(tmp_path: Path) -> None:
    client, token = _authed_client(tmp_path)
    resp = client.get("/api/v1/papers/pap_does_not_exist/profile", headers=_auth_headers(token))
    assert resp.status_code == 404


def test_get_profile_after_analysis_returns_the_persisted_profile_without_re_extracting(
    tmp_path: Path, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)
    _save_working_key(client, token, monkeypatch)
    _mock_llm(monkeypatch, _VALID_EXTRACTION_JSON)

    analyzed = client.post(f"/api/v1/papers/{paper_id}/analyze", headers=_auth_headers(token))
    assert analyzed.status_code == 200
    profile_id = analyzed.json()["profile"]["profile_id"]

    # No LLM key/mock is needed for this call: GET must read back the
    # already-persisted profile rather than re-running extraction.
    fetched = client.get(f"/api/v1/papers/{paper_id}/profile", headers=_auth_headers(token))
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["profile_id"] == profile_id
    assert body["domain"]["value"] == "Retrieval-Augmented Generation"
    assert body["keywords"] == ["rag", "retrieval"]


def test_patch_profile_without_existing_profile_returns_404(tmp_path: Path, normal_paper_pdf_bytes: bytes) -> None:
    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)
    resp = client.patch(f"/api/v1/papers/{paper_id}/profile", json={"domain": "x"}, headers=_auth_headers(token))
    assert resp.status_code == 404


def test_patch_profile_marks_touched_fields_user_edited(
    tmp_path: Path, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)
    _save_working_key(client, token, monkeypatch)
    _mock_llm(monkeypatch, _VALID_EXTRACTION_JSON)
    client.post(f"/api/v1/papers/{paper_id}/analyze", headers=_auth_headers(token))

    resp = client.patch(
        f"/api/v1/papers/{paper_id}/profile",
        json={"domain": "Computer Vision", "datasets": ["ImageNet"]},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    profile = resp.json()["profile"]
    assert profile["domain"]["value"] == "Computer Vision"
    assert profile["domain"]["status"] == "user_edited"
    assert profile["datasets"]["items"][0]["value"] == "ImageNet"
    assert profile["datasets"]["items"][0]["status"] == "user_edited"
    # an untouched field keeps its extracted value (as every profile reads: a sentence)
    assert profile["research_problem"]["value"] == "Grounding LLM answers in evidence."


def test_a_provider_failure_while_analysing_is_named_and_its_call_counted(
    tmp_path: Path, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.profile.pipeline as pipeline_module
    from app.db import repository as repo
    from app.db.session import get_session_factory
    from app.domain.user import LlmProvider
    from app.llm.providers.openai_compat import OpenAiCompatClient

    client, token = _authed_client(tmp_path)
    paper_id = _upload_and_wait(client, token, normal_paper_pdf_bytes)
    _save_working_key(client, token, monkeypatch)

    def broke(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "Insufficient Balance"}})

    monkeypatch.setattr(
        pipeline_module,
        "get_llm_client",
        lambda provider: OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(broke))),
    )
    resp = client.post(f"/api/v1/papers/{paper_id}/analyze", headers=_auth_headers(token))
    error = resp.json()["detail"]["error"]
    assert resp.status_code == 502 and (error["code"], error["kind"]) == ("provider_error", "insufficient_balance")
    assert error["message"] == "Your Groq account is out of credit. Top it up, then try again."

    db = get_session_factory()()
    try:
        user = repo.get_user_by_email(db, "researcher@example.com")
        assert user is not None
        assert [(c.feature, c.error_kind) for c in repo.list_llm_calls(db, user.id)] == [("profile", "insufficient_balance")]
    finally:
        db.close()
