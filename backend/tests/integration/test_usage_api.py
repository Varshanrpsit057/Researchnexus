"""`GET /api/v1/usage` (remediation Phase 5): the provider's own token counts
from the usage ledger, over a clear range, by feature, model and workspace --
and never a cost."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.db.session import get_session_factory
from app.domain.usage import LlmCall
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.main import create_app
from app.services.normalize.canonical import title_hash
from tests.auth_helpers import sign_in


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _sign_in(c: TestClient, email: str) -> tuple[dict[str, str], str]:
    token = sign_in(c, email)
    headers = {"Authorization": f"Bearer {token}"}
    return headers, c.get("/api/v1/me", headers=headers).json()["id"]


def _workspace(owner_id: str, workspace_id: str, title: str) -> None:
    db = get_session_factory()()
    try:
        pid = f"pap_{workspace_id}"
        repo.save_paper(db, PaperORM(id=pid, title=title, title_hash=title_hash(pid), has_full_text=True))
        repo.create_workspace(
            db,
            ResearchWorkspace(
                workspace_id=workspace_id, owner_id=owner_id, title=title, seed_paper_id=pid, seed_profile_id="prof",
                papers=[WorkspacePaper(workspace_id=workspace_id, paper_id=pid, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
            ),
        )
    finally:
        db.close()


_n = 0


def _call(owner_id: str, *, days_ago: float, feature: str = "chat", workspace_id: str | None = None, **kw: object) -> None:
    global _n
    _n += 1
    fields: dict = {"provider": "deepseek", "model": "deepseek-flash", "prompt_tokens": 1000, "completion_tokens": 200} | kw
    db = get_session_factory()()
    try:
        repo.record_llm_call(
            db,
            LlmCall(
                id=f"llm_{_n}", owner_id=owner_id, workspace_id=workspace_id, feature=feature,
                created_at=datetime.now(timezone.utc) - timedelta(days=days_ago), **fields,
            ),
        )
    finally:
        db.close()


def test_nothing_used_yet_is_all_zeros_over_a_stated_range(tmp_path: Path) -> None:
    c = _client(tmp_path)
    headers, _ = _sign_in(c, "new@example.com")
    body = c.get("/api/v1/usage", headers=headers).json()
    assert body["range"]["key"] == "30d" and body["range"]["days"] == 30
    since = datetime.fromisoformat(body["range"]["since"])
    until = datetime.fromisoformat(body["range"]["until"])
    assert since.utcoffset() == timedelta(0) and until - since == timedelta(days=30)
    assert body["totals"] == {
        "calls": 0, "failed_calls": 0, "unreported_calls": 0, "prompt_tokens": 0, "cached_prompt_tokens": 0,
        "completion_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0,
    }
    assert body["first_call_at"] is None and body["by_feature"] == [] and body["by_model"] == [] and body["by_workspace"] == []
    assert "cost" not in str(body)  # no price is known, so none is claimed


def test_usage_is_summed_from_the_ledger_over_each_range(tmp_path: Path) -> None:
    c = _client(tmp_path)
    headers, me = _sign_in(c, "r@example.com")
    _, other = _sign_in(c, "someone-else@example.com")
    _workspace(me, "ws_a", "Attendance systems")

    _call(me, days_ago=1, workspace_id="ws_a", cached_prompt_tokens=600)
    _call(me, days_ago=2, feature="gaps", workspace_id="ws_a", prompt_tokens=4000, completion_tokens=900, reasoning_tokens=500)
    _call(me, days_ago=20, feature="profile", provider="gemini", model="gemini-2.5-flash", prompt_tokens=3000, completion_tokens=300)
    _call(me, days_ago=3, feature="chat", workspace_id="ws_a", ok=False, error_kind="rate_limited", prompt_tokens=0, completion_tokens=0)
    _call(me, days_ago=4, feature="chat", workspace_id="ws_gone", prompt_tokens=0, completion_tokens=0)  # answered, usage not reported
    _call(me, days_ago=60, feature="other")
    _call(me, days_ago=400, feature="chat", workspace_id="ws_a")
    _call(other, days_ago=1, feature="chat", prompt_tokens=99_999)  # never anyone else's

    def get(range_key: str) -> dict:
        r = c.get(f"/api/v1/usage?range={range_key}", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    week = get("7d")
    assert week["totals"] == {
        "calls": 4, "failed_calls": 1, "unreported_calls": 1, "prompt_tokens": 5000, "cached_prompt_tokens": 600,
        "completion_tokens": 1100, "reasoning_tokens": 500, "total_tokens": 6100,
    }
    assert [(f["feature"], f["calls"], f["total_tokens"]) for f in week["by_feature"]] == [("gaps", 1, 4900), ("chat", 3, 1200)]
    assert [(w["workspace_id"], w["title"], w["total_tokens"]) for w in week["by_workspace"]] == [
        ("ws_a", "Attendance systems", 6100),
        ("ws_gone", None, 0),  # a deleted workspace's usage stays counted, without a name
    ]

    month = get("30d")
    assert month["totals"]["calls"] == 5 and month["totals"]["total_tokens"] == 9400
    assert [(m["provider"], m["model"], m["total_tokens"]) for m in month["by_model"]] == [
        ("deepseek", "deepseek-flash", 6100),
        ("gemini", "gemini-2.5-flash", 3300),
    ]
    assert {w["workspace_id"] for w in month["by_workspace"]} == {"ws_a", "ws_gone", None}  # None: a paper's own profile

    assert get("90d")["totals"]["calls"] == 6
    everything = get("all")
    assert everything["range"]["since"] is None and everything["range"]["days"] is None
    assert everything["totals"]["calls"] == 7
    first = datetime.fromisoformat(everything["first_call_at"])
    assert first.utcoffset() == timedelta(0) and (datetime.now(timezone.utc) - first).days == 400


def test_one_workspaces_usage(tmp_path: Path) -> None:
    c = _client(tmp_path)
    headers, me = _sign_in(c, "r@example.com")
    intruder, _ = _sign_in(c, "intruder@example.com")
    _workspace(me, "ws_a", "A")
    _workspace(me, "ws_b", "B")
    _call(me, days_ago=1, workspace_id="ws_a")
    _call(me, days_ago=1, feature="gaps", workspace_id="ws_a")
    _call(me, days_ago=1, workspace_id="ws_b", prompt_tokens=50_000)

    body = c.get("/api/v1/usage?workspace_id=ws_a&range=7d", headers=headers).json()
    assert body["workspace_id"] == "ws_a" and "by_workspace" not in body
    assert body["totals"]["calls"] == 2 and body["totals"]["total_tokens"] == 2400
    assert {f["feature"] for f in body["by_feature"]} == {"chat", "gaps"}

    assert c.get("/api/v1/usage?workspace_id=ws_a", headers=intruder).status_code == 404
    assert c.get("/api/v1/usage?workspace_id=ws_missing", headers=headers).status_code == 404


def test_usage_needs_a_known_range_and_a_signed_in_user(tmp_path: Path) -> None:
    c = _client(tmp_path)
    headers, _ = _sign_in(c, "r@example.com")
    assert c.get("/api/v1/usage?range=1y", headers=headers).status_code == 422
    assert c.get("/api/v1/usage").status_code == 401
