from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_session_factory
from app.domain.profile import ProfileField, ProfileList, ResearchProfile, SourceSpan
from app.domain.user import LlmCapabilities, LlmProvider, LlmTestResult
from app.main import create_app
from app.services.normalize.canonical import title_hash


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
        key_vault_secret=Fernet.generate_key().decode(),
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _token(c: TestClient, email: str = "r@example.com") -> str:
    return c.post("/api/v1/auth/session", json={"email": email, "password": "x"}).json()["token"]


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def _add_paper(db, pid: str, *, limitation: str, method: str, problem: str = "dense retrieval") -> None:
    from app.db.models import PaperORM

    repo.save_paper(db, PaperORM(id=pid, title=pid.upper(), title_hash=title_hash(pid), has_full_text=True, year=2022))
    repo.upsert_profile(
        db,
        ResearchProfile(
            profile_id=f"prof_{pid}", paper_id=pid, title=pid.upper(), abstract="ab",
            domain=ProfileField(value="IR"),
            research_problem=ProfileField(value=problem, source_span=SourceSpan(paper_id=pid, section="Intro", char_start=1, char_end=9, quote=problem)),
            methods=ProfileList(items=[ProfileField(value=method, source_span=SourceSpan(paper_id=pid, section="Body", char_start=10, char_end=20, quote=method))]),
            limitations=ProfileList(items=[ProfileField(value=limitation, source_span=SourceSpan(paper_id=pid, section="Body", char_start=30, char_end=45, quote=limitation))]),
        ),
    )


def _seed_ws(c: TestClient, token: str) -> str:
    factory = get_session_factory()
    db = factory()
    try:
        _add_paper(db, "pap_seed", limitation="evaluated only on English", method="bm25")
        _add_paper(db, "p2", limitation="evaluated only on English", method="tf-idf")
        _add_paper(db, "p3", limitation="small model", method="contrastive pretraining")
    finally:
        db.close()
    wid = c.post("/api/v1/workspaces", json={"title": "W", "seed_paper_id": "pap_seed"}, headers=_h(token)).json()["workspace_id"]
    c.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": ["p2", "p3"]}, headers=_h(token))
    return wid


def _save_key(c: TestClient, token: str, mp: pytest.MonkeyPatch) -> None:
    import app.routers.settings_keys as sk

    async def _probe(provider: object, api_key: str, *, transport: object = None) -> LlmTestResult:
        return LlmTestResult(success=True, latency_ms=1, capabilities=LlmCapabilities(json_mode=True, context_tokens=8192, streaming=True))

    mp.setattr(sk, "probe", _probe)
    assert c.put("/api/v1/settings/llm-keys", json={"provider": "groq", "api_key": "sk-x"}, headers=_h(token)).status_code == 200


def _mock_llm(mp: pytest.MonkeyPatch, *, self_support: bool = True) -> None:
    import app.llm.session as sm

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "phrase a research gap" in body:
            if "limitation" in body and "English" in body:
                payload: object = {
                    "statement": "Two papers report the same evaluated only on English limitation and none resolves it.",
                    "why_unaddressed": "The evaluated only on English limitation is stated but not addressed.",
                    "proposed_direction": "Evaluate beyond English.",
                }
            elif "contrastive pretraining" in body:
                payload = {
                    "statement": "No workspace paper applies contrastive pretraining to dense retrieval.",
                    "why_unaddressed": "The papers study dense retrieval but none adopt contrastive pretraining.",
                    "proposed_direction": "Apply contrastive pretraining to the shared setting.",
                }
            else:
                payload = {"statement": "The papers differ on this facet.", "why_unaddressed": "Each differs.", "proposed_direction": "Align them."}
        elif "fully supports the statement" in body:
            payload = {"results": [{"index": 0, "supported": self_support}]}
        else:
            payload = {}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 4, "completion_tokens": 2}})

    def fake(provider: object):  # noqa: ANN202
        from app.llm.providers.openai_compat import OpenAiCompatClient

        return OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    mp.setattr(sm, "get_llm_client", fake)


def test_gaps_requires_key_and_tenant(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    assert c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token)).status_code == 409
    other = _token(c, "x@example.com")
    assert c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(other)).status_code == 404


def test_gaps_run_persists_evidence_grounded_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)

    r = c.post(f"/api/v1/workspaces/{wid}/gaps", json={"min_supporting_papers": 2}, headers=_h(token))
    assert r.status_code == 202
    job_id = r.json()["job"]["job_id"]
    assert c.get(f"/api/v1/jobs/{job_id}", headers=_h(token)).json()["status"] == "succeeded"

    gaps = c.get(f"/api/v1/workspaces/{wid}/gaps", headers=_h(token)).json()["gaps"]
    assert gaps
    for g in gaps:
        assert len(g["supporting_papers"]) >= 2
        assert g["supporting_evidence"] and all(e["span"]["quote"] for e in g["supporting_evidence"])
        assert g["confidence"] in {"high", "medium", "low"}  # band, never a percentage
        assert isinstance(g["confidence_basis"], dict) and "self_support" in g["confidence_basis"]
        assert g["self_support_passed"] is True
        assert g["user_state"] == "candidate"
    assert "GENERALIZATION_GAP" in {g["gap_type"] for g in gaps}


def test_a_finished_run_says_what_happened_to_every_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, self_support=False)

    job_id = c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token)).json()["job"]["job_id"]
    progress = c.get(f"/api/v1/jobs/{job_id}", headers=_h(token)).json()["progress"]

    # nothing survived, and the job says why rather than just "0"
    assert progress["count"] == "0"
    candidates = int(progress["candidates"])
    assert candidates > 0
    accounted = sum(
        int(progress[k])
        for k in ("dropped_insufficient_evidence", "skipped_rejected", "kept_accepted", "unchecked", "not_checked")
    )
    assert int(progress["dropped_self_support"]) == candidates - accounted
    assert (progress["profiled"], progress["unprofiled"], progress["profile_failed"]) == ("0", "0", "0")
    assert progress["stage"] == "done"


def test_gap_times_read_back_as_utc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)
    c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token))

    gaps = c.get(f"/api/v1/workspaces/{wid}/gaps", headers=_h(token)).json()["gaps"]
    assert gaps and all(g["generated_at"].endswith(("Z", "+00:00")) for g in gaps)


def test_gaps_bad_type_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)
    assert c.post(f"/api/v1/workspaces/{wid}/gaps", json={"gap_types": ["NOT_A_GAP"]}, headers=_h(token)).status_code == 422


def test_accept_and_reject_and_state_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)
    c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token))
    gaps = c.get(f"/api/v1/workspaces/{wid}/gaps", headers=_h(token)).json()["gaps"]
    g0, g1 = gaps[0]["gap_id"], gaps[1]["gap_id"] if len(gaps) > 1 else gaps[0]["gap_id"]

    acc = c.post(f"/api/v1/workspaces/{wid}/gaps/{g0}", json={"user_state": "accepted"}, headers=_h(token))
    assert acc.status_code == 200 and acc.json()["user_state"] == "accepted"
    if g1 != g0:
        c.post(f"/api/v1/workspaces/{wid}/gaps/{g1}", json={"user_state": "rejected"}, headers=_h(token))

    assert {g["gap_id"] for g in c.get(f"/api/v1/workspaces/{wid}/gaps?state=accepted", headers=_h(token)).json()["gaps"]} == {g0}
    assert c.get(f"/api/v1/workspaces/{wid}/gaps?state=bogus", headers=_h(token)).status_code == 422
    assert c.post(f"/api/v1/workspaces/{wid}/gaps/gap_ghost", json={"user_state": "accepted"}, headers=_h(token)).status_code == 404


def test_rerun_is_deterministic_and_keeps_rejections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)

    c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token))
    first = c.get(f"/api/v1/workspaces/{wid}/gaps", headers=_h(token)).json()["gaps"]
    victim = first[0]["gap_id"]
    c.post(f"/api/v1/workspaces/{wid}/gaps/{victim}", json={"user_state": "rejected"}, headers=_h(token))

    c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token))
    second = c.get(f"/api/v1/workspaces/{wid}/gaps", headers=_h(token)).json()["gaps"]
    by_id = {g["gap_id"]: g for g in second}
    assert by_id[victim]["user_state"] == "rejected"  # not re-proposed as a candidate
    # the other gaps are byte-identical bar the timestamp
    def _strip(g: dict) -> dict:
        g = dict(g)
        g.pop("generated_at", None)
        return g
    first_candidates = sorted((_strip(g) for g in first if g["gap_id"] != victim), key=lambda g: g["gap_id"])
    second_candidates = sorted((_strip(g) for g in second if g["gap_id"] != victim), key=lambda g: g["gap_id"])
    assert first_candidates == second_candidates


# --- remediation Phase 3: a failed run always says why ---------------------


def test_a_rejected_key_fails_the_job_with_a_named_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.llm.session as sm
    from app.llm.providers.openai_compat import OpenAiCompatClient

    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)

    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Authentication Fails"}})

    monkeypatch.setattr(sm, "get_llm_client", lambda provider: OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(rejected))))
    job_id = c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token)).json()["job"]["job_id"]
    job = c.get(f"/api/v1/jobs/{job_id}", headers=_h(token)).json()

    assert job["status"] == "failed"
    assert job["error"] == "Groq rejected the saved API key. Check it in Settings, or save a new one."
    assert (job["progress"]["stage"], job["progress"]["error_code"], job["progress"]["error_kind"]) == ("failed", "provider_error", "auth")
    assert c.get(f"/api/v1/workspaces/{wid}/gaps", headers=_h(token)).json()["gaps"] == []


def test_a_run_past_its_limit_fails_with_what_to_do_next(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.llm.session as sm
    from app.llm.providers.openai_compat import OpenAiCompatClient

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
        key_vault_secret=Fernet.generate_key().decode(),
        gap_run_timeout_s=0.3,
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    c = TestClient(app)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(sm, "get_llm_client", lambda provider: OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(slow))))
    job_id = c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token)).json()["job"]["job_id"]
    job = c.get(f"/api/v1/jobs/{job_id}", headers=_h(token)).json()
    assert job["status"] == "failed" and job["progress"]["error_code"] == "timeout"
    assert "was stopped. Papers read so far are kept; run it again to continue." in job["error"]


def test_a_runs_model_calls_are_counted_as_gap_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)

    job_id = c.post(f"/api/v1/workspaces/{wid}/gaps", json={}, headers=_h(token)).json()["job"]["job_id"]
    db = get_session_factory()()
    try:
        user = repo.get_user_by_email(db, "r@example.com")
        assert user is not None
        calls = repo.list_llm_calls(db, user.id, workspace_id=wid)
    finally:
        db.close()
    assert calls and {(k.feature, k.job_id) for k in calls} == {("gaps", job_id)}
    assert sum(k.prompt_tokens for k in calls) == 4 * len(calls)
