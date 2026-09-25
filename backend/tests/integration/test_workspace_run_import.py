"""Regression: importing one discovery run into several workspaces.

Importing a run used to re-stamp its trail rows with the newest workspace,
so creating a second workspace from the same discovery results silently
moved every connection -- and every accept/reject decision -- out of the
first one, emptying its trail and graph (migration 0014 fixed the schema).
"""

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


def _make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _token(client: TestClient, email: str) -> str:
    return client.post("/api/v1/auth/session", json={"email": email, "password": "x"}).json()["token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_run(*, owner_email: str | None = None) -> None:
    """An analysed seed paper and a discovery run with two trail edges."""
    db = get_session_factory()()
    try:
        from app.db.models import PaperORM

        repo.save_paper(db, PaperORM(id="pap_seed", title="Seed", title_hash=title_hash("seed"), has_full_text=True))
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id="prof_seed", paper_id="pap_seed", title="Seed", abstract="a",
                domain=ProfileField(value="RAG"), research_problem=ProfileField(value="grounding"),
            ),
        )
        owner = repo.get_user_by_email(db, owner_email) if owner_email else None
        repo.create_search_run(
            db, SearchRun(run_id="run_1", seed_paper_id="pap_seed", owner_id=owner.id if owner else None)
        )
        edges = []
        for i, (title, rtype) in enumerate([("Rival", RelationshipType.COMPETING), ("Earlier", RelationshipType.FOUNDATIONAL)]):
            tgt = repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title)))
            edges.append(
                TrailEdge(
                    edge_id=f"edge_{i}", run_id="run_1", source_paper_id="pap_seed", target_paper_id=tgt,
                    relationship_type=rtype, detection_method=DetectionMethod.RULE,
                    evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote=f"quote {i}"), role="target_claim")],
                    confidence=Confidence.MEDIUM,
                )
            )
        repo.save_trail_edges(db, "run_1", edges)
    finally:
        db.close()


def _create(client: TestClient, token: str, title: str) -> str:
    resp = client.post(
        "/api/v1/workspaces",
        json={"title": title, "seed_paper_id": "pap_seed", "import_run_id": "run_1"},
        headers=_h(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["workspace_id"]


def _states(client: TestClient, token: str, wid: str) -> dict[str, str]:
    """target title -> review state, over every connection in the workspace trail."""
    trail = client.get(f"/api/v1/workspaces/{wid}/trail?state=all", headers=_h(token)).json()
    return {e["target"]["title"]: e["edge"]["user_state"] for group in trail["groups"].values() for e in group}


def _edge_id(client: TestClient, token: str, wid: str, title: str) -> str:
    trail = client.get(f"/api/v1/workspaces/{wid}/trail?state=all", headers=_h(token)).json()
    return next(e["edge"]["edge_id"] for g in trail["groups"].values() for e in g if e["target"]["title"] == title)


def test_a_second_workspace_from_the_same_run_leaves_the_first_ones_trail_and_decisions_alone(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client, "researcher@example.com")
    _seed_run()

    first = _create(client, token, "First")
    rival_first = _edge_id(client, token, first, "Rival")
    client.post(f"/api/v1/workspaces/{first}/trail/{rival_first}", json={"user_state": "accepted"}, headers=_h(token))
    earlier_first = _edge_id(client, token, first, "Earlier")
    client.post(f"/api/v1/workspaces/{first}/trail/{earlier_first}", json={"user_state": "rejected"}, headers=_h(token))
    before_graph = client.get(f"/api/v1/workspaces/{first}/graph", headers=_h(token)).json()

    second = _create(client, token, "Second")

    # the first workspace is exactly as it was: both connections, both decisions
    assert _states(client, token, first) == {"Rival": "accepted", "Earlier": "rejected"}
    after_graph = client.get(f"/api/v1/workspaces/{first}/graph", headers=_h(token)).json()
    assert after_graph["edge_count"] == before_graph["edge_count"] == 1
    # the second has its own copy of the run's trail, unreviewed
    assert _states(client, token, second) == {"Rival": "pending", "Earlier": "pending"}
    rival_second = _edge_id(client, token, second, "Rival")
    assert rival_second != rival_first

    # decisions stay independent in both directions
    client.post(f"/api/v1/workspaces/{second}/trail/{rival_second}", json={"user_state": "rejected"}, headers=_h(token))
    assert _states(client, token, first)["Rival"] == "accepted"
    client.post(f"/api/v1/workspaces/{first}/trail/{rival_first}", json={"user_state": "pending"}, headers=_h(token))
    assert _states(client, token, second)["Rival"] == "rejected"
    # and one workspace cannot decide on the other's rows
    wrong = client.post(f"/api/v1/workspaces/{second}/trail/{rival_first}", json={"user_state": "accepted"}, headers=_h(token))
    assert wrong.status_code == 404


def test_deleting_a_workspace_keeps_the_other_workspaces_trail(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client, "researcher@example.com")
    _seed_run()
    first = _create(client, token, "First")
    second = _create(client, token, "Second")
    client.post(
        f"/api/v1/workspaces/{second}/trail/{_edge_id(client, token, second, 'Rival')}",
        json={"user_state": "accepted"},
        headers=_h(token),
    )

    assert client.delete(f"/api/v1/workspaces/{first}", headers=_h(token)).status_code == 204
    assert _states(client, token, second) == {"Rival": "accepted", "Earlier": "pending"}

    # a new import picks up the released primaries without the deleted workspace's decisions
    third = _create(client, token, "Third")
    assert _states(client, token, third) == {"Rival": "pending", "Earlier": "pending"}
    assert client.delete(f"/api/v1/workspaces/{second}", headers=_h(token)).status_code == 204
    assert _states(client, token, third) == {"Rival": "pending", "Earlier": "pending"}


def test_another_users_run_is_not_imported_and_their_trail_is_untouched(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    owner = _token(client, "owner@example.com")
    intruder = _token(client, "intruder@example.com")
    _seed_run(owner_email="owner@example.com")
    mine = _create(client, owner, "Mine")
    client.post(
        f"/api/v1/workspaces/{mine}/trail/{_edge_id(client, owner, mine, 'Rival')}",
        json={"user_state": "accepted"},
        headers=_h(owner),
    )

    theirs = _create(client, intruder, "Theirs")

    ws = client.get(f"/api/v1/workspaces/{theirs}", headers=_h(intruder)).json()
    assert ws["source_run_id"] is None
    assert _states(client, intruder, theirs) == {}
    assert _states(client, owner, mine) == {"Rival": "accepted", "Earlier": "pending"}
