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


def _seed_ws_with_gap(c: TestClient, token: str, *, gap_state: str = "accepted") -> tuple[str, str]:
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
            affected_methods=["contrastive pretraining"],
            confidence=Confidence.MEDIUM, self_support_passed=True,
        )
        repo.save_gaps(db, wid, [gap], owner_id=_owner_id(wid))
        if gap_state != "candidate":
            repo.set_gap_user_state(db, "gap_1", workspace_id=wid, owner_id=_owner_id(wid), state=GapUserState(gap_state))
    finally:
        db.close()
    return wid, "gap_1"


def _save_key(c: TestClient, token: str, mp: pytest.MonkeyPatch) -> None:
    import app.routers.settings_keys as sk

    async def _probe(provider: object, api_key: str, *, transport: object = None) -> LlmTestResult:
        return LlmTestResult(success=True, latency_ms=1, capabilities=LlmCapabilities(json_mode=True, context_tokens=8192, streaming=True))

    mp.setattr(sk, "probe", _probe)
    assert c.put("/api/v1/settings/llm-keys", json={"provider": "groq", "api_key": "sk-x"}, headers=_h(token)).status_code == 200


def _mock_llm(mp: pytest.MonkeyPatch, *, grounded: bool = True) -> None:
    import app.llm.session as sm

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "next-step research directions" in body:
            if grounded:
                payload: object = {"directions": [
                    {"proposal": "Apply contrastive pretraining to dense retrieval.", "motivation": "The papers study dense retrieval but skip contrastive pretraining.", "suggested_method": "contrastive pretraining", "possible_dataset": None, "evaluation_strategy": "Evaluate on the shared setting.", "risks": ["May not transfer."]},
                ]}
            else:
                payload = {"directions": [
                    {"proposal": "Apply quantum annealing to dense retrieval.", "motivation": "Quantum annealing already solves this reliably.", "suggested_method": "quantum annealing", "possible_dataset": None, "evaluation_strategy": "Evaluate.", "risks": []},
                ]}
        elif "Rate the DIRECTION" in body:
            payload = {"novelty": 3, "specificity": 4, "feasibility": 2, "groundedness": 5}
        else:
            payload = {}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    def fake(provider: object):  # noqa: ANN202
        from app.llm.providers.openai_compat import OpenAiCompatClient

        return OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    mp.setattr(sm, "get_llm_client", fake)


def test_directions_requires_key_tenant_and_nonempty_gap_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_gap(c, token)
    assert c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token)).status_code == 409
    other = _token(c, "x@example.com")
    _save_key(c, token, monkeypatch)
    assert c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(other)).status_code == 404
    assert c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": []}, headers=_h(token)).status_code == 422


def test_directions_generated_only_from_accepted_gap_and_persisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_gap(c, token, gap_state="accepted")
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)

    r = c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["generated"] == 1
    directions = body["directions"]
    assert len(directions) == 1
    d = directions[0]
    assert d["gap_id"] == gap_id
    assert d["kind"] in {"evidence_backed_inference", "llm_hypothesis"}
    assert d["critique"] and set(d["critique"]) == {"novelty", "specificity", "feasibility", "groundedness"}
    assert d["confidence"] in {"high", "medium", "low"}
    assert d["supporting_evidence"]
    assert d["user_state"] == "candidate"

    listed = c.get(f"/api/v1/workspaces/{wid}/directions", headers=_h(token)).json()["directions"]
    assert len(listed) == 1 and listed[0]["direction_id"] == d["direction_id"]
    # SQLite drops a timestamp's zone; without it a browser reads the time as local
    assert listed[0]["generated_at"].endswith(("Z", "+00:00")), listed[0]["generated_at"]


def test_directions_skipped_for_a_non_accepted_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_gap(c, token, gap_state="candidate")
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)

    r = c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] == 0
    assert body["skipped_not_accepted"] == 1
    assert c.get(f"/api/v1/workspaces/{wid}/directions", headers=_h(token)).json()["directions"] == []


def test_unsupported_llm_direction_is_dropped_via_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_gap(c, token, gap_state="accepted")
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, grounded=False)

    r = c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] == 0
    assert body["dropped_unsupported"] == 1


def test_accept_reject_and_state_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, gap_id = _seed_ws_with_gap(c, token, gap_state="accepted")
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch)
    c.post(f"/api/v1/workspaces/{wid}/directions", json={"gap_ids": [gap_id]}, headers=_h(token))
    did = c.get(f"/api/v1/workspaces/{wid}/directions", headers=_h(token)).json()["directions"][0]["direction_id"]

    acc = c.post(f"/api/v1/workspaces/{wid}/directions/{did}", json={"user_state": "accepted"}, headers=_h(token))
    assert acc.status_code == 200 and acc.json()["user_state"] == "accepted"
    assert {d["direction_id"] for d in c.get(f"/api/v1/workspaces/{wid}/directions?state=accepted", headers=_h(token)).json()["directions"]} == {did}
    assert c.get(f"/api/v1/workspaces/{wid}/directions?state=bogus", headers=_h(token)).status_code == 422
    assert c.post(f"/api/v1/workspaces/{wid}/directions/dir_ghost", json={"user_state": "accepted"}, headers=_h(token)).status_code == 404
