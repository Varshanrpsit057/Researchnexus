from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_session_factory
from app.domain.candidate import NormalizedCandidate
from app.domain.chunk import PaperChunk
from app.domain.profile import ProfileField, ResearchProfile
from app.main import create_app
from app.services.normalize.canonical import title_hash


def _make_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "test.db"
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{db_path}",
        jwt_secret="test-jwt-secret",
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _token(client: TestClient, email: str = "researcher@example.com") -> str:
    return client.post("/api/v1/auth/session", json={"email": email, "password": "x"}).json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_analysed_paper(*, paper_id: str = "pap_seed") -> None:
    factory = get_session_factory()
    db = factory()
    try:
        from app.db.models import PaperORM

        repo.save_paper(
            db,
            PaperORM(
                id=paper_id,
                title="Retrieval-Augmented Generation",
                title_hash=title_hash(f"seed-{paper_id}"),
                has_full_text=True,
            ),
        )
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id=f"prof_{paper_id}",
                paper_id=paper_id,
                title="Retrieval-Augmented Generation",
                abstract="We combine parametric and non-parametric memory.",
                domain=ProfileField(value="RAG"),
                research_problem=ProfileField(value="grounding LLM answers"),
            ),
        )
    finally:
        db.close()


def _discovered_paper(title: str) -> str:
    factory = get_session_factory()
    db = factory()
    try:
        pid = repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title)))
        repo.save_chunks(
            db,
            [PaperChunk(chunk_id=f"chk_{pid}", paper_id=pid, char_start=0, char_end=18, text="retrieval reranking", token_count=2)],
        )
        return pid
    finally:
        db.close()


def _create_ws(client: TestClient, token: str, **body: object) -> dict:
    payload: dict[str, object] = {"title": "RAG survey", "seed_paper_id": "pap_seed"}
    payload.update(body)
    resp = client.post("/api/v1/workspaces", json=payload, headers=_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_requires_auth(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post("/api/v1/workspaces", json={"title": "x", "seed_paper_id": "pap_seed"})
    assert resp.status_code == 401


def test_create_then_get_workspace(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()

    ws = _create_ws(client, token)
    assert ws["workspace_id"].startswith("ws_")
    assert ws["seed_paper_id"] == "pap_seed"
    assert [p["role"] for p in ws["papers"]] == ["seed"]

    got = client.get(f"/api/v1/workspaces/{ws['workspace_id']}", headers=_headers(token))
    assert got.status_code == 200
    body = got.json()
    assert body["counts"] == {"papers": 1, "edges": 0, "gaps": 0, "directions": 0, "comparisons": 0}
    # no estimated spend or cap: usage is GET /usage, in the provider's own tokens (remediation Phase 5)
    assert not {"cost_used", "cost_used_usd", "token_budget_usd", "tokens_used"} & body.keys()


def test_workspace_times_read_back_as_utc(tmp_path: Path) -> None:
    # SQLite drops a timestamp's zone; without it a browser reads the time as local
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    ws = _create_ws(client, token)

    got = client.get(f"/api/v1/workspaces/{ws['workspace_id']}", headers=_headers(token)).json()
    listed = client.get("/api/v1/workspaces", headers=_headers(token)).json()["workspaces"][0]
    for body in (got, listed):
        assert body["created_at"].endswith(("Z", "+00:00")), body["created_at"]
        assert body["updated_at"].endswith(("Z", "+00:00")), body["updated_at"]


def test_the_workspace_list_names_each_seed_and_counts_its_work(tmp_path: Path) -> None:
    # remediation 2026-10-06: the list page shows what each workspace holds, not only ids
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    ws = _create_ws(client, token)
    [listed] = client.get("/api/v1/workspaces", headers=_headers(token)).json()["workspaces"]
    assert listed["workspace_id"] == ws["workspace_id"]
    assert listed["seed_title"] == "Retrieval-Augmented Generation"
    assert listed["counts"] == {"papers": 1, "edges": 0, "gaps": 0, "directions": 0, "comparisons": 0}


def test_create_with_unanalysed_seed_is_409(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    factory = get_session_factory()
    db = factory()
    try:
        from app.db.models import PaperORM

        repo.save_paper(db, PaperORM(id="pap_raw", title="Raw", title_hash=title_hash("Raw"), has_full_text=False))
    finally:
        db.close()
    resp = client.post(
        "/api/v1/workspaces", json={"title": "x", "seed_paper_id": "pap_raw"}, headers=_headers(token)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "conflict"


def test_create_with_missing_seed_is_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    resp = client.post(
        "/api/v1/workspaces", json={"title": "x", "seed_paper_id": "pap_ghost"}, headers=_headers(token)
    )
    assert resp.status_code == 404


def test_workspace_is_invisible_to_other_tenants(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    owner = _token(client, "owner@example.com")
    intruder = _token(client, "intruder@example.com")
    _seed_analysed_paper()
    ws = _create_ws(client, owner)
    wid = ws["workspace_id"]

    assert client.get(f"/api/v1/workspaces/{wid}", headers=_headers(intruder)).status_code == 404
    assert client.patch(
        f"/api/v1/workspaces/{wid}", json={"title": "hijack"}, headers=_headers(intruder)
    ).status_code == 404
    assert client.delete(f"/api/v1/workspaces/{wid}", headers=_headers(intruder)).status_code == 404
    assert client.get("/api/v1/workspaces", headers=_headers(intruder)).json()["workspaces"] == []


def test_patch_workspace_updates_title(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    wid = _create_ws(client, token)["workspace_id"]

    resp = client.patch(f"/api/v1/workspaces/{wid}", json={"title": "new"}, headers=_headers(token))
    assert resp.status_code == 200
    assert resp.json()["title"] == "new"


def test_a_spending_cap_from_an_older_client_is_ignored_not_an_error(tmp_path: Path) -> None:
    # the USD cap is retired (remediation Phase 5): it rested on a flat-rate guess
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    created = client.post(
        "/api/v1/workspaces", json={"title": "x", "seed_paper_id": "pap_seed", "token_budget_usd": 3}, headers=_headers(token)
    )
    assert created.status_code == 201
    wid = created.json()["workspace_id"]
    resp = client.patch(f"/api/v1/workspaces/{wid}", json={"title": "kept", "token_budget_usd": 0}, headers=_headers(token))
    assert resp.status_code == 200
    assert resp.json()["title"] == "kept" and "token_budget_usd" not in resp.json()


def test_add_pin_tag_annotate_and_remove_paper(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    wid = _create_ws(client, token)["workspace_id"]
    p1 = _discovered_paper("Candidate One")

    add = client.post(
        f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [p1]}, headers=_headers(token)
    )
    assert add.status_code == 201
    assert add.json()["added"] == [p1]

    # duplicate add is idempotent
    again = client.post(
        f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [p1]}, headers=_headers(token)
    )
    assert again.status_code == 201 and again.json()["added"] == []

    patched = client.patch(
        f"/api/v1/workspaces/{wid}/papers/{p1}",
        json={"pinned": True, "tags": ["method", "method", " baseline "], "note": "  key ref ", "order": 1},
        headers=_headers(token),
    )
    assert patched.status_code == 200
    wp = patched.json()
    assert wp["pinned"] is True
    assert wp["tags"] == ["method", "baseline"]
    assert wp["note"] == "key ref"
    assert wp["order"] == 1

    # bounded: a runaway note or tag list is refused, not stored
    for body in ({"note": "x" * 4001}, {"tags": [f"t{i}" for i in range(31)]}, {"tags": ["y" * 61]}):
        assert client.patch(f"/api/v1/workspaces/{wid}/papers/{p1}", json=body, headers=_headers(token)).status_code == 422

    removed = client.delete(f"/api/v1/workspaces/{wid}/papers/{p1}", headers=_headers(token))
    assert removed.status_code == 200
    assert p1 not in [p["paper_id"] for p in removed.json()["papers"]]


def test_cannot_remove_seed_and_unknown_paper_is_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    wid = _create_ws(client, token)["workspace_id"]

    assert client.delete(
        f"/api/v1/workspaces/{wid}/papers/pap_seed", headers=_headers(token)
    ).status_code == 409
    assert client.delete(
        f"/api/v1/workspaces/{wid}/papers/pap_ghost", headers=_headers(token)
    ).status_code == 404
    assert client.post(
        f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": ["pap_ghost"]}, headers=_headers(token)
    ).status_code == 404


def test_delete_workspace_is_204_and_gone(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    wid = _create_ws(client, token)["workspace_id"]

    assert client.delete(f"/api/v1/workspaces/{wid}", headers=_headers(token)).status_code == 204
    assert client.get(f"/api/v1/workspaces/{wid}", headers=_headers(token)).status_code == 404


def test_trail_grouped_read_and_accept_reject(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()

    # a discovery run + one trail edge the workspace will import
    factory = get_session_factory()
    db = factory()
    try:
        from app.domain.candidate import SearchRun
        from app.domain.profile import Confidence, SourceSpan
        from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge

        tgt = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Rival", title_hash=title_hash("Rival")))
        repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id="pap_seed"))
        repo.save_trail_edges(
            db,
            "run_1",
            [
                TrailEdge(
                    edge_id="edge_1", run_id="run_1", source_paper_id="pap_seed", target_paper_id=tgt,
                    relationship_type=RelationshipType.COMPETING, detection_method=DetectionMethod.RULE,
                    evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote="q"), role="similarity_signal")],
                    confidence=Confidence.MEDIUM,
                )
            ],
        )
    finally:
        db.close()

    wid = _create_ws(client, token, import_run_id="run_1")["workspace_id"]

    trail = client.get(f"/api/v1/workspaces/{wid}/trail", headers=_headers(token)).json()
    assert trail["seed_paper_id"] == "pap_seed"
    assert len(trail["groups"]["COMPETING"]) == 1
    edge_id = trail["groups"]["COMPETING"][0]["edge"]["edge_id"]

    rej = client.post(
        f"/api/v1/workspaces/{wid}/trail/{edge_id}", json={"user_state": "rejected"}, headers=_headers(token)
    )
    assert rej.status_code == 200 and rej.json()["user_state"] == "rejected"

    # hidden by default now, visible with ?state=rejected
    assert client.get(f"/api/v1/workspaces/{wid}/trail", headers=_headers(token)).json()["groups"]["COMPETING"] == []
    shown = client.get(f"/api/v1/workspaces/{wid}/trail?state=rejected", headers=_headers(token)).json()
    assert len(shown["groups"]["COMPETING"]) == 1
    # ?state=all returns every edge in one read, rejected included, each with its state
    everything = client.get(f"/api/v1/workspaces/{wid}/trail?state=all", headers=_headers(token)).json()
    assert [e["edge"]["user_state"] for e in everything["groups"]["COMPETING"]] == ["rejected"]

    assert client.get(f"/api/v1/workspaces/{wid}/trail?state=bogus", headers=_headers(token)).status_code == 422
    assert client.post(
        f"/api/v1/workspaces/{wid}/trail/edge_ghost", json={"user_state": "accepted"}, headers=_headers(token)
    ).status_code == 404
