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
from app.domain.gap import GapEvidence, GapType, GapUserState, ResearchGap
from app.domain.profile import Confidence, ProfileField, ResearchProfile, SourceSpan
from app.domain.user import LlmCapabilities, LlmProvider, LlmTestResult
from app.main import create_app
from app.services.normalize.canonical import title_hash
from tests.auth_helpers import sign_in


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
    return sign_in(c, email)


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def _owner_id(workspace_id: str) -> str:
    from app.db.models import WorkspaceORM

    factory = get_session_factory()
    db = factory()
    try:
        row = db.get(WorkspaceORM, workspace_id)
        assert row is not None
        return row.owner_id
    finally:
        db.close()


def _seed_ws_with_accepted_gap(c: TestClient, token: str) -> tuple[str, str]:
    from app.db.models import PaperORM

    factory = get_session_factory()
    db = factory()
    try:
        repo.save_paper(db, PaperORM(id="pap_seed", title="Seed", title_hash=title_hash("seed"), has_full_text=True))
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id="prof_seed", paper_id="pap_seed", title="Seed", abstract="ab",
                domain=ProfileField(value="IR"), research_problem=ProfileField(value="dense retrieval"),
            ),
        )
    finally:
        db.close()

    r = c.post("/api/v1/workspaces", json={"title": "W", "seed_paper_id": "pap_seed"}, headers=_h(token))
    assert r.status_code == 201, r.text
    wid = r.json()["workspace_id"]

    db = factory()
    try:
        gap = ResearchGap(
            gap_id="gap_1", workspace_id=wid,
            statement="No workspace paper applies contrastive pretraining to dense retrieval.",
            gap_type=GapType.METHOD_GAP, supporting_papers=["p1", "p2"],
            supporting_evidence=[
                GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="we study dense retrieval")),
                GapEvidence(paper_id="p2", span=SourceSpan(paper_id="p2", quote="we also study dense retrieval")),
            ],
            why_unaddressed="The papers study dense retrieval but none adopt contrastive pretraining.",
            proposed_direction="Apply contrastive pretraining to the shared setting.",
            affected_methods=["contrastive pretraining"], confidence=Confidence.MEDIUM, self_support_passed=True,
        )
        repo.save_gaps(db, wid, [gap], owner_id=_owner_id(wid))
        repo.set_gap_user_state(db, "gap_1", workspace_id=wid, owner_id=_owner_id(wid), state=GapUserState.ACCEPTED)
    finally:
        db.close()
    return wid, "gap_1"


def _save_key(c: TestClient, token: str, mp: pytest.MonkeyPatch) -> None:
    import app.routers.settings_keys as sk

    async def _probe(provider: object, api_key: str, *, transport: object = None) -> LlmTestResult:
        return LlmTestResult(success=True, latency_ms=1, capabilities=LlmCapabilities(json_mode=True, context_tokens=8192, streaming=True))

    mp.setattr(sk, "probe", _probe)
    assert c.put("/api/v1/settings/llm-keys", json={"provider": "groq", "api_key": "sk-x"}, headers=_h(token)).status_code == 200


def _mock_directions_llm(mp: pytest.MonkeyPatch) -> None:
    import app.llm.session as sm

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "next-step research directions" in body:
            payload: object = {"directions": [
                {"proposal": "Apply contrastive pretraining to dense retrieval.", "motivation": "The papers study dense retrieval but skip contrastive pretraining.", "suggested_method": "contrastive pretraining", "possible_dataset": None, "evaluation_strategy": "Evaluate.", "risks": []},
            ]}
        elif "Rate the DIRECTION" in body:
            payload = {"novelty": 3, "specificity": 4, "feasibility": 2, "groundedness": 5}
        else:
            payload = {}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 12, "completion_tokens": 8}})

    def fake(provider: object):  # noqa: ANN202
        from app.llm.providers.openai_compat import OpenAiCompatClient

        return OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    mp.setattr(sm, "get_llm_client", fake)


def test_activity_is_empty_for_a_fresh_workspace(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _gap_id = _seed_ws_with_accepted_gap(c, token)

    r = c.get(f"/api/v1/workspaces/{wid}/activity", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {"stage_runs": []}


def test_generating_directions_writes_an_activity_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_accepted_gap(c, token)
    _save_key(c, token, monkeypatch)
    _mock_directions_llm(monkeypatch)

    gen = c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token))
    assert gen.status_code == 200, gen.text

    r = c.get(f"/api/v1/workspaces/{wid}/activity", headers=_h(token))
    assert r.status_code == 200
    rows = r.json()["stage_runs"]
    assert len(rows) == 1
    assert rows[0]["stage"] == "directions"
    assert rows[0]["ok"] is True
    assert rows[0]["tokens_prompt"] > 0
    assert "error" not in rows[0] or rows[0]["error"] is None


def test_a_stage_run_keeps_the_tokens_its_model_calls_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # remediation Phase 5: from the provider's own counts, the same the usage report sums
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_accepted_gap(c, token)
    _save_key(c, token, monkeypatch)
    _mock_directions_llm(monkeypatch)
    assert c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token)).status_code == 200

    [run] = c.get(f"/api/v1/workspaces/{wid}/activity", headers=_h(token)).json()["stage_runs"]
    usage = c.get(f"/api/v1/usage?workspace_id={wid}", headers=_h(token)).json()
    [directions] = usage["by_feature"]
    assert directions["feature"] == "directions"  # named after the stage, not "other"
    calls = directions["calls"]
    assert calls >= 2  # a proposal and its rating, each 12 in / 8 out
    assert (run["tokens_prompt"], run["tokens_completion"]) == (12 * calls, 8 * calls)
    assert (directions["prompt_tokens"], directions["completion_tokens"]) == (12 * calls, 8 * calls)


def test_activity_can_filter_by_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_accepted_gap(c, token)
    _save_key(c, token, monkeypatch)
    _mock_directions_llm(monkeypatch)
    c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token))

    assert len(c.get(f"/api/v1/workspaces/{wid}/activity?stage=directions", headers=_h(token)).json()["stage_runs"]) == 1
    assert len(c.get(f"/api/v1/workspaces/{wid}/activity?stage=rag", headers=_h(token)).json()["stage_runs"]) == 0


def test_activity_rejects_an_unknown_stage(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _gap_id = _seed_ws_with_accepted_gap(c, token)
    assert c.get(f"/api/v1/workspaces/{wid}/activity?stage=not_a_stage", headers=_h(token)).status_code == 422


def test_activity_is_invisible_to_other_tenants(tmp_path: Path) -> None:
    c = _client(tmp_path)
    owner = _token(c, "owner@example.com")
    intruder = _token(c, "intruder@example.com")
    wid, _gap_id = _seed_ws_with_accepted_gap(c, owner)

    assert c.get(f"/api/v1/workspaces/{wid}/activity", headers=_h(intruder)).status_code == 404


def test_activity_404s_for_a_missing_workspace(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    assert c.get("/api/v1/workspaces/ws_ghost/activity", headers=_h(token)).status_code == 404


def test_activity_never_leaks_prompt_or_response_bodies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_accepted_gap(c, token)
    _save_key(c, token, monkeypatch)
    _mock_directions_llm(monkeypatch)
    c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token))

    row = c.get(f"/api/v1/workspaces/{wid}/activity", headers=_h(token)).json()["stage_runs"][0]
    assert set(row) == {
        "id", "owner_id", "workspace_id", "job_id", "stage", "tool", "input_hash", "output_hash",
        "tokens_prompt", "tokens_completion", "latency_ms", "ok", "error", "ts",
    }
