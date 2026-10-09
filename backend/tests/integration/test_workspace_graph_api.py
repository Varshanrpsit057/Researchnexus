from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_session_factory
from app.domain.candidate import NormalizedCandidate, SearchRun
from app.domain.profile import Confidence, ProfileField, ResearchProfile, SourceSpan
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge
from app.main import create_app
from app.services.normalize.canonical import title_hash
from tests.auth_helpers import sign_in


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
    return sign_in(client, email)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_analysed_paper(*, paper_id: str = "pap_seed") -> None:
    factory = get_session_factory()
    db = factory()
    try:
        from app.db.models import PaperORM

        repo.save_paper(
            db,
            PaperORM(id=paper_id, title="Retrieval-Augmented Generation", title_hash=title_hash(f"seed-{paper_id}"), has_full_text=True),
        )
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id=f"prof_{paper_id}", paper_id=paper_id, title="Retrieval-Augmented Generation",
                abstract="We combine parametric and non-parametric memory.",
                domain=ProfileField(value="RAG"), research_problem=ProfileField(value="grounding LLM answers"),
            ),
        )
    finally:
        db.close()


def _create_ws(client: TestClient, token: str, **body: object) -> dict:
    payload: dict[str, object] = {"title": "RAG survey", "seed_paper_id": "pap_seed"}
    payload.update(body)
    resp = client.post("/api/v1/workspaces", json=payload, headers=_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_run_with_trail_edge(rtype: RelationshipType = RelationshipType.COMPETING, *, target_title: str = "Rival") -> str:
    """A discovery run with one seed->target trail edge; returns the target paper id.

    Importing the run onto a workspace (`import_run_id=`) attaches the edge
    but does NOT make the target a workspace member: the graph shows it as a
    connected paper until it is `POST .../papers`-ed in, which is also what
    accepts the edge (`_accept_edges_for_target`).
    """
    factory = get_session_factory()
    db = factory()
    try:
        tgt = repo.upsert_discovered_paper(db, NormalizedCandidate(title=target_title, title_hash=title_hash(target_title)))
        repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id="pap_seed"))
        repo.save_trail_edges(
            db, "run_1",
            [
                TrailEdge(
                    edge_id="edge_1", run_id="run_1", source_paper_id="pap_seed", target_paper_id=tgt,
                    relationship_type=rtype, detection_method=DetectionMethod.RULE,
                    evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote="a supporting sentence"), role="similarity_signal")],
                    confidence=Confidence.MEDIUM,
                )
            ],
        )
        return tgt
    finally:
        db.close()


def test_graph_requires_auth(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _seed_analysed_paper()
    token = _token(client)
    wid = _create_ws(client, token)["workspace_id"]
    assert client.get(f"/api/v1/workspaces/{wid}/graph").status_code == 401


def test_graph_of_a_fresh_workspace_has_only_the_seed_node(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    wid = _create_ws(client, token)["workspace_id"]

    resp = client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace_id"] == wid
    assert body["node_count"] == 1
    assert body["edge_count"] == 0
    assert body["nodes"][0]["id"] == "pap_seed"
    assert body["nodes"][0]["type"] == "PAPER"
    assert body["nodes"][0]["label"] == "Retrieval-Augmented Generation"


def test_graph_is_invisible_to_other_tenants(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    owner = _token(client, "owner@example.com")
    intruder = _token(client, "intruder@example.com")
    _seed_analysed_paper()
    wid = _create_ws(client, owner)["workspace_id"]

    assert client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(intruder)).status_code == 404


def test_missing_workspace_is_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    assert client.get("/api/v1/workspaces/ws_ghost/graph", headers=_headers(token)).status_code == 404


def test_an_imported_run_shows_its_connections_and_adding_the_paper_makes_it_a_member(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    tgt = _seed_run_with_trail_edge(RelationshipType.COMPETING)
    wid = _create_ws(client, token, import_run_id="run_1")["workspace_id"]

    # Regression: the edge used to be invisible until its paper was added.
    before = client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token)).json()
    assert before["node_count"] == 2 and before["edge_count"] == 1
    target = next(n for n in before["nodes"] if n["id"] == tgt)
    assert target["in_workspace"] is False and target["role"] is None
    assert target["label"] == "Rival"
    edge = before["edges"][0]
    assert edge["src"] == "pap_seed" and edge["dst"] == tgt
    assert edge["type"] == "COMPETES_WITH"
    assert edge["relationship_types"] == ["COMPETING"]
    assert edge["trail_edge_ids"] == ["edge_1"]
    assert edge["user_state"] == "pending"
    assert edge["evidence"][0]["quote"] == "a supporting sentence"

    add = client.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [tgt]}, headers=_headers(token))
    assert add.status_code == 201, add.text

    after = client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token)).json()
    assert after["node_count"] == 2
    nodes = {n["id"]: n for n in after["nodes"]}
    assert nodes["pap_seed"]["role"] == "seed"
    assert nodes[tgt]["in_workspace"] is True and nodes[tgt]["role"] == "related"
    assert after["edge_count"] == 1
    assert after["edges"][0]["user_state"] == "accepted"  # joining accepted it


def test_an_edge_accepted_in_the_trail_review_stays_in_the_graph_without_adding_the_paper(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    tgt = _seed_run_with_trail_edge(RelationshipType.FOUNDATIONAL, target_title="An Earlier Paper")
    wid = _create_ws(client, token, import_run_id="run_1")["workspace_id"]

    accepted = client.post(f"/api/v1/workspaces/{wid}/trail/edge_1", json={"user_state": "accepted"}, headers=_headers(token))
    assert accepted.status_code == 200, accepted.text

    graph = client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token)).json()
    assert graph["edge_count"] == 1
    assert graph["edges"][0]["type"] == "CITES"
    assert graph["edges"][0]["user_state"] == "accepted"
    assert next(n for n in graph["nodes"] if n["id"] == tgt)["in_workspace"] is False


def test_removing_a_paper_leaves_it_connected_until_its_edge_is_rejected(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    tgt = _seed_run_with_trail_edge()
    wid = _create_ws(client, token, import_run_id="run_1")["workspace_id"]
    client.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [tgt]}, headers=_headers(token))

    removed = client.delete(f"/api/v1/workspaces/{wid}/papers/{tgt}", headers=_headers(token))
    assert removed.status_code == 200

    after = client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token)).json()
    assert after["node_count"] == 2 and after["edge_count"] == 1
    assert next(n for n in after["nodes"] if n["id"] == tgt)["in_workspace"] is False

    client.post(f"/api/v1/workspaces/{wid}/trail/edge_1", json={"user_state": "rejected"}, headers=_headers(token))
    rejected = client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token)).json()
    assert rejected["node_count"] == 1
    assert rejected["edge_count"] == 0


def test_rejecting_a_trail_edge_removes_it_from_the_graph_but_keeps_the_node(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    tgt = _seed_run_with_trail_edge()
    wid = _create_ws(client, token, import_run_id="run_1")["workspace_id"]
    client.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [tgt]}, headers=_headers(token))
    assert client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token)).json()["edge_count"] == 1

    rej = client.post(
        f"/api/v1/workspaces/{wid}/trail/edge_1", json={"user_state": "rejected"}, headers=_headers(token)
    )
    assert rej.status_code == 200

    after = client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token)).json()
    assert after["node_count"] == 2  # both papers are still workspace members
    assert after["edge_count"] == 0  # the rejected edge is gone


def _owner_of(db, workspace_id: str) -> str:  # noqa: ANN001
    from app.db.models import WorkspaceORM

    row = db.get(WorkspaceORM, workspace_id)
    assert row is not None
    return row.owner_id


def test_graph_is_persisted_to_the_workspace_row(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    wid = _create_ws(client, token)["workspace_id"]
    fetched = client.get(f"/api/v1/workspaces/{wid}/graph", headers=_headers(token)).json()

    factory = get_session_factory()
    db = factory()
    try:
        owner_id = _owner_of(db, wid)
        stored = repo.get_workspace_graph(db, wid, owner_id)
    finally:
        db.close()

    assert stored is not None
    assert stored.node_count == fetched["node_count"]
    assert stored.workspace_id == wid
