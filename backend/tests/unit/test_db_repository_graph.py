from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import WorkspaceORM
from app.domain.candidate import NormalizedCandidate
from app.domain.graph import GraphEdge, GraphEdgeType, GraphNode, GraphNodeType, ResearchGraph
from app.domain.profile import Confidence, SourceSpan
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.services.normalize.canonical import title_hash


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(conn: object, _rec: object) -> None:
        cur = conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _workspace(db: Session) -> tuple[str, str]:
    uid = "usr_1"
    repo.create_user(db, user_id=uid, email="u@example.com")
    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    repo.create_workspace(
        db,
        ResearchWorkspace(
            workspace_id="ws_1", owner_id=uid, title="W", seed_paper_id=seed, seed_profile_id="prof",
            papers=[WorkspacePaper(workspace_id="ws_1", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
        ),
    )
    return "ws_1", uid


def _graph(wid: str) -> ResearchGraph:
    return ResearchGraph(
        workspace_id=wid,
        nodes=[GraphNode(id="pap_seed", type=GraphNodeType.PAPER, label="Seed", paper_ids=["pap_seed"])],
        edges=[
            GraphEdge(
                src="pap_seed", dst="pap_a", type=GraphEdgeType.SIMILAR,
                evidence=[SourceSpan(paper_id="pap_a", quote="q")], confidence=Confidence.MEDIUM,
            )
        ],
    )


def test_get_workspace_graph_is_none_before_any_graph_is_set(db: Session) -> None:
    wid, uid = _workspace(db)
    assert repo.get_workspace_graph(db, wid, uid) is None


def test_set_and_get_workspace_graph_round_trip(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.set_workspace_graph(db, wid, uid, _graph(wid))
    restored = repo.get_workspace_graph(db, wid, uid)
    assert restored is not None
    assert restored.workspace_id == wid
    assert restored.node_count == 1
    assert restored.edges[0].type == GraphEdgeType.SIMILAR


def test_graph_is_stored_as_plain_json_on_the_workspace_row(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.set_workspace_graph(db, wid, uid, _graph(wid))
    row = db.get(WorkspaceORM, wid)
    assert row is not None and isinstance(row.graph_json, dict)
    assert row.graph_json["node_count"] == 1


def test_set_workspace_graph_is_owner_gated(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.set_workspace_graph(db, wid, "usr_other", _graph(wid))
    assert repo.get_workspace_graph(db, wid, uid) is None


def test_get_workspace_graph_is_owner_gated(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.set_workspace_graph(db, wid, uid, _graph(wid))
    assert repo.get_workspace_graph(db, wid, "usr_other") is None


def test_setting_a_new_graph_overwrites_the_old_one(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.set_workspace_graph(db, wid, uid, _graph(wid))
    empty = ResearchGraph(workspace_id=wid)
    repo.set_workspace_graph(db, wid, uid, empty)
    restored = repo.get_workspace_graph(db, wid, uid)
    assert restored is not None and restored.node_count == 0
