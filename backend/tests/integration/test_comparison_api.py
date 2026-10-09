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
        d.pop("created_at", None)  # when each run happened, not what it found
        for row in d["rows"]:
            for cell in row["cells"].values():
                cell.pop("claim_id", None)  # identity, derived from the (fresh) comparison_id
        return d

    assert _strip_ids(a) == _strip_ids(b)


def test_an_abstract_only_paper_joins_the_comparison_through_its_abstract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: a paper found by discovery (no PDF) was never chunked, so its
    # comparison row was all empty cells, indistinguishable from "not stated".
    c = _client(tmp_path)
    token = _token(c)
    wid, _ = _seed_ws(c, token)
    abstract = "We propose a late-interaction reranker evaluated on MS MARCO with MRR at 10."
    db = get_session_factory()()
    try:
        p3 = repo.upsert_discovered_paper(db, NormalizedCandidate(title="C", title_hash=title_hash("C"), abstract=abstract))
    finally:
        db.close()
    assert c.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [p3]}, headers=_h(token)).status_code == 201
    db = get_session_factory()()
    try:
        assert [ch.section for ch in repo.get_chunks_for_paper(db, p3)] == ["Abstract"]  # joining indexed it
    finally:
        db.close()

    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, {
        "pap_seed": {"cells": [{"column": "dataset", "value": "NQ", "chunk_id": "a0", "quote": "on the NQ dataset"}]},
        p3: {"cells": [
            {"column": "dataset", "value": "MS MARCO", "chunk_id": f"chk_{p3}_abstract", "quote": "evaluated on MS MARCO"},
            {"column": "method", "value": "graph walk", "chunk_id": f"chk_{p3}_abstract", "quote": "a graph walk"},
        ]},
    })
    r = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": ["pap_seed", p3], "schema": ["method", "dataset"]}, headers=_h(token))
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["rows"] if x["paper_id"] == p3)
    assert row["cells"]["dataset"]["status"] == "found"
    assert row["cells"]["dataset"]["span"]["section"] == "Abstract" and row["cells"]["dataset"]["grounding"] == "abstract"
    assert row["cells"]["method"]["status"] == "unsupported" and row["cells"]["method"]["text"] is None
    seed_row = next(x for x in r.json()["rows"] if x["paper_id"] == "pap_seed")
    assert seed_row["cells"]["method"]["status"] == "not_stated"
    # statuses persist
    latest = c.get(f"/api/v1/workspaces/{wid}/compare", headers=_h(token)).json()
    assert next(x for x in latest["rows"] if x["paper_id"] == p3)["cells"]["method"]["status"] == "unsupported"


def test_comparison_table_and_word_export_are_the_same_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # remediation Phase 12: the page draws `/table`; `/export.docx` writes that same table to Word
    from tests.docx_reader import read_docx

    c = _client(tmp_path)
    token = _token(c)
    wid, p2 = _seed_ws(c, token)
    _save_key(c, token, monkeypatch)
    _mock_llm(monkeypatch, {
        "pap_seed": {"cells": [{"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"}]},
    })
    cmp_id = c.post(f"/api/v1/workspaces/{wid}/compare", json={"paper_ids": [], "schema": ["method", "dataset"]}, headers=_h(token)).json()["comparison_id"]

    table = c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}/table", headers=_h(token))
    assert table.status_code == 200, table.text
    t = table.json()
    assert [p["paper_id"] for p in t["papers"]] == ["pap_seed", p2]
    assert [p["title"] for p in t["papers"]] == ["A", "B"]
    assert t["papers"][0]["kind"] == "seed" and t["papers"][1]["kind"] == "member"
    assert [r["label"] for r in t["rows"]] == ["Method", "Datasets"]
    assert [c_["text"] for c_ in t["rows"][0]["cells"]] == ["dense retrieval", "Not stated"]

    export = c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}/export.docx", headers=_h(token))
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert export.headers["content-disposition"] == 'attachment; filename="Comparison - W.docx"'
    # the page (another origin) may read the file name
    from_page = c.get(
        f"/api/v1/workspaces/{wid}/compare/{cmp_id}/export.docx",
        headers={**_h(token), "Origin": "http://localhost:3000"},
    )
    assert "content-disposition" in from_page.headers["access-control-expose-headers"].lower()
    grid = read_docx(export.content).tables[0]
    expected = [
        [[t["corner"]], *([p["title"], p["meta"]] for p in t["papers"])],
        *([[r["label"]], *([cell["text"]] if cell["note"] is None else [cell["text"], cell["note"]] for cell in r["cells"])] for r in t["rows"]),
    ]
    assert grid == expected

    # the columns shown on the page are the columns exported
    only_seed = c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}/export.docx?papers=pap_seed", headers=_h(token))
    assert [cell[0] for cell in read_docx(only_seed.content).tables[0][0]] == ["Field", "A"]
    assert c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}/table?papers=pap_nope", headers=_h(token)).status_code == 422
    assert c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}/export.docx?papers=", headers=_h(token)).status_code == 422
    assert c.get(f"/api/v1/workspaces/{wid}/compare/cmp_missing/table", headers=_h(token)).status_code == 404
    other = _token(c, "z@example.com")
    assert c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}/export.docx", headers=_h(other)).status_code == 404
    assert c.get(f"/api/v1/workspaces/{wid}/compare/{cmp_id}/table").status_code == 401
