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
from app.domain.candidate import NormalizedCandidate
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.profile import ProfileField, ProfileList, ResearchProfile
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


def _seed_ws(c: TestClient, token: str) -> tuple[str, str]:
    """Returns (workspace_id, second_paper_id)."""
    factory = get_session_factory()
    db = factory()
    try:
        from app.db.models import PaperORM

        repo.save_paper(db, PaperORM(id="pap_seed", title="A", title_hash=title_hash("A"), has_full_text=True))
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id="prof_seed", paper_id="pap_seed", title="A", abstract="ab",
                domain=ProfileField(value="IR"), research_problem=ProfileField(value="retrieval"),
                methods=ProfileList(items=[ProfileField(value="dense retrieval")]),
                datasets=ProfileList(items=[ProfileField(value="NQ")]),
            ),
        )
        repo.save_chunks(db, [PaperChunk(chunk_id="a0", paper_id="pap_seed", section="Method", page=1, char_start=0, char_end=55, kind=ChunkKind.BODY, text="We use dense retrieval on the NQ dataset in this work.", token_count=10)])
        p2 = repo.upsert_discovered_paper(db, NormalizedCandidate(title="B", title_hash=title_hash("B")))
        repo.save_chunks(db, [PaperChunk(chunk_id="b0", paper_id=p2, section="Method", page=1, char_start=0, char_end=33, kind=ChunkKind.BODY, text="We use BM25 sparse retrieval here.", token_count=6)])
    finally:
        db.close()

    wid = c.post("/api/v1/workspaces", json={"title": "W", "seed_paper_id": "pap_seed"}, headers=_h(token)).json()["workspace_id"]
    c.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [p2]}, headers=_h(token))
    return wid, p2


def _save_key(c: TestClient, token: str, mp: pytest.MonkeyPatch) -> None:
    import app.routers.settings_keys as sk

    async def _probe(provider: object, api_key: str, *, transport: object = None) -> LlmTestResult:
        return LlmTestResult(success=True, latency_ms=1, capabilities=LlmCapabilities(json_mode=True, context_tokens=8192, streaming=True))

    mp.setattr(sk, "probe", _probe)
    assert c.put("/api/v1/settings/llm-keys", json={"provider": "groq", "api_key": "sk-x"}, headers=_h(token)).status_code == 200


def _mock_llm(mp: pytest.MonkeyPatch, cells_by_paper: dict[str, object]) -> None:
    import app.llm.session as sm

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        payload: object = {"cells": []}
        for pid, cells in cells_by_paper.items():
            if f"PAPER: {pid}" in body:
                payload = cells
                break
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 8, "completion_tokens": 4}})

    def fake(provider: object):  # noqa: ANN202
        from app.llm.providers.openai_compat import OpenAiCompatClient

        return OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    mp.setattr(sm, "get_llm_client", fake)


def test_compare_requires_key_and_tenant(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _ = _seed_ws(c, token)
    assert c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": []}, headers=_h(token)).status_code == 409
    other = _token(c, "x@example.com")
    assert c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": []}, headers=_h(other)).status_code == 404


def test_compare_needs_at_least_two_papers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _ = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, {})
    assert c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": ["pap_seed"]}, headers=_h(token)).status_code == 422


def test_compare_returns_grounded_table_and_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, p2 = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, {
        "pap_seed": {"cells": [
            {"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"},
            {"column": "dataset", "value": "NQ", "chunk_id": "a0", "quote": "the NQ dataset"},
        ]},
        p2: {"cells": [{"column": "method", "value": "sparse retrieval", "chunk_id": "b0", "quote": "the authors used a sparse method"}]},  # bad quote -> rejected
    })

    r = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": [], "schema": ["method", "dataset"]}, headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == ["method", "dataset"]
    seed_row = next(row for row in body["rows"] if row["paper_id"] == "pap_seed")
    assert seed_row["cells"]["method"]["text"] == "dense retrieval"
    assert seed_row["cells"]["method"]["span"]["paper_id"] == "pap_seed"
    assert seed_row["cells"]["method"]["claim_id"]
    p2_row = next(row for row in body["rows"] if row["paper_id"] == p2)
    assert p2_row["cells"]["method"]["text"] is None  # bad quote -> missing, not hallucinated
    assert body["coverage"] == 0.5  # 2 grounded / (2 papers * 2 cols)

    cmp_id = body["comparison_id"]
    got = c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}", headers=_h(token))
    assert got.status_code == 200 and got.json()["coverage"] == 0.5
    assert c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}", headers=_h(_token(c, "z@example.com"))).status_code == 404


def test_compare_default_schema_is_derived_from_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _ = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, {})
    r = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": [], "schema": None}, headers=_h(token))
    assert r.status_code == 200
    assert r.json()["schema"] == ["problem", "method", "dataset"]  # seed profile facets
    assert r.json()["generated_by"] == "deterministic_union"


def test_get_latest_comparison_before_any_run_returns_404(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _ = _seed_ws(c, token)
    assert c.get(f"/api/v1/workspaces/{wid}/compare", headers=_h(token)).status_code == 404


def test_get_latest_comparison_returns_the_most_recent_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _ = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, {"pap_seed": {"cells": [{"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"}]}})

    first = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": [], "schema": ["method"]}, headers=_h(token)).json()
    second = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": [], "schema": ["method", "dataset"]}, headers=_h(token)).json()
    assert first["comparison_id"] != second["comparison_id"]

    latest = c.get(f"/api/v1/workspaces/{wid}/compare", headers=_h(token))
    assert latest.status_code == 200
    assert latest.json()["comparison_id"] == second["comparison_id"]
    assert latest.json()["schema"] == ["method", "dataset"]

    assert c.get(f"/api/v1/workspaces/{wid}/compare", headers=_h(_token(c, "z@example.com"))).status_code == 404


def test_compare_output_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _ = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, {"pap_seed": {"cells": [{"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"}]}})
    a = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": [], "schema": ["method", "dataset"]}, headers=_h(token)).json()
    b = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": [], "schema": ["method", "dataset"]}, headers=_h(token)).json()

    def _strip_ids(d: dict) -> dict:
        d.pop("comparison_id", None)
        for row in d["rows"]:
            for cell in row["cells"].values():
                cell.pop("claim_id", None)  # identity, derived from the (fresh) comparison_id
        return d

    assert _strip_ids(a) == _strip_ids(b)
