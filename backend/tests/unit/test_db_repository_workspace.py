from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperRelationshipORM, WorkspacePaperORM
from app.domain.candidate import NormalizedCandidate, SearchRun
from app.domain.profile import Confidence, SourceSpan
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge, UserState
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


def _user(db: Session, uid: str = "usr_1") -> str:
    repo.create_user(db, user_id=uid, email=f"{uid}@example.com")
    return uid


def _paper(db: Session, title: str) -> str:
    return repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title)))


def _ws(owner_id: str, seed_id: str, *, wid: str = "ws_1", run_id: str | None = None) -> ResearchWorkspace:
    return ResearchWorkspace(
        workspace_id=wid,
        owner_id=owner_id,
        title="RAG survey",
        seed_paper_id=seed_id,
        seed_profile_id="prof_seed",
        source_run_id=run_id,
        papers=[
            WorkspacePaper(
                workspace_id=wid, paper_id=seed_id, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED
            )
        ],
    )


def test_create_and_get_workspace_round_trip(db: Session) -> None:
    uid = _user(db)
    seed = _paper(db, "Seed")
    repo.create_workspace(db, _ws(uid, seed))

    ws = repo.get_workspace(db, "ws_1", uid)
    assert ws is not None
    assert ws.title == "RAG survey"
    assert ws.owner_id == uid
    assert [p.paper_id for p in ws.papers] == [seed]
    assert ws.papers[0].role is WorkspacePaperRole.SEED
    assert ws.token_budget_usd == 5.0


def test_get_workspace_is_tenant_isolated(db: Session) -> None:
    owner = _user(db, "usr_owner")
    other = _user(db, "usr_other")
    seed = _paper(db, "Seed")
    repo.create_workspace(db, _ws(owner, seed))

    assert repo.get_workspace(db, "ws_1", owner) is not None
    assert repo.get_workspace(db, "ws_1", other) is None
    assert repo.list_workspaces(db, other) == []
    assert len(repo.list_workspaces(db, owner)) == 1


def test_update_workspace_only_touches_given_fields(db: Session) -> None:
    uid = _user(db)
    seed = _paper(db, "Seed")
    repo.create_workspace(db, _ws(uid, seed))

    updated = repo.update_workspace(db, "ws_1", uid, title="new title")
    assert updated is not None and updated.title == "new title"
    assert updated.token_budget_usd == 5.0

    updated = repo.update_workspace(db, "ws_1", uid, token_budget_usd=12.5)
    assert updated is not None and updated.token_budget_usd == 12.5 and updated.title == "new title"

    assert repo.update_workspace(db, "ws_missing", uid, title="x") is None
    assert repo.update_workspace(db, "ws_1", "usr_other", title="x") is None


def test_delete_workspace_cascades_papers_and_clears_trail_membership(db: Session) -> None:
    uid = _user(db)
    seed = _paper(db, "Seed")
    tgt = _paper(db, "Target")
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed))
    repo.save_trail_edges(
        db,
        "run_1",
        [
            TrailEdge(
                edge_id="edge_1",
                run_id="run_1",
                source_paper_id=seed,
                target_paper_id=tgt,
                relationship_type=RelationshipType.SIMILAR,
                detection_method=DetectionMethod.RULE,
                evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote="q"), role="similarity_signal")],
                confidence=Confidence.MEDIUM,
            )
        ],
    )
    repo.create_workspace(db, _ws(uid, seed, run_id="run_1"))
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_1", owner_id=uid)
    assert len(repo.get_workspace_trail_edges(db, "ws_1")) == 1

    assert repo.delete_workspace(db, "ws_1", uid) is True
    assert repo.get_workspace(db, "ws_1", uid) is None
    assert db.query(WorkspacePaperORM).filter_by(workspace_id="ws_1").count() == 0
    # the trail edge itself survives (still run-scoped) but loses workspace membership
    edge = db.query(PaperRelationshipORM).filter_by(id="edge_1").one()
    assert edge.workspace_id is None and edge.owner_id is None


def test_add_get_remove_workspace_paper(db: Session) -> None:
    uid = _user(db)
    seed = _paper(db, "Seed")
    p1 = _paper(db, "P1")
    repo.create_workspace(db, _ws(uid, seed))

    repo.add_workspace_paper(
        db, WorkspacePaper(workspace_id="ws_1", paper_id=p1, added_by=AddedBy.TRAIL), owner_id=uid
    )
    assert repo.get_workspace_paper(db, "ws_1", p1) is not None
    assert {p.paper_id for p in repo.list_workspace_papers(db, "ws_1")} == {seed, p1}

    assert repo.remove_workspace_paper(db, "ws_1", p1) is True
    assert repo.get_workspace_paper(db, "ws_1", p1) is None
    assert repo.remove_workspace_paper(db, "ws_1", p1) is False


def test_add_duplicate_workspace_paper_raises_integrity_error(db: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    uid = _user(db)
    seed = _paper(db, "Seed")
    p1 = _paper(db, "P1")
    repo.create_workspace(db, _ws(uid, seed))
    repo.add_workspace_paper(db, WorkspacePaper(workspace_id="ws_1", paper_id=p1, added_by=AddedBy.MANUAL), owner_id=uid)
    with pytest.raises(IntegrityError):
        repo.add_workspace_paper(
            db, WorkspacePaper(workspace_id="ws_1", paper_id=p1, added_by=AddedBy.MANUAL), owner_id=uid
        )


def test_update_workspace_paper_pins_tags_notes_and_reorders(db: Session) -> None:
    uid = _user(db)
    seed = _paper(db, "Seed")
    p1 = _paper(db, "P1")
    repo.create_workspace(db, _ws(uid, seed))
    repo.add_workspace_paper(db, WorkspacePaper(workspace_id="ws_1", paper_id=p1, added_by=AddedBy.MANUAL), owner_id=uid)

    wp = repo.update_workspace_paper(
        db, "ws_1", p1, {"pinned": True, "tags": ["method", "baseline"], "note": "key comparison", "order": 3}
    )
    assert wp is not None
    assert wp.pinned is True
    assert wp.tags == ["method", "baseline"]
    assert wp.note == "key comparison"
    assert wp.order == 3

    # partial update leaves other fields intact
    wp = repo.update_workspace_paper(db, "ws_1", p1, {"pinned": False})
    assert wp is not None and wp.pinned is False and wp.tags == ["method", "baseline"] and wp.order == 3

    assert repo.update_workspace_paper(db, "ws_1", "pap_missing", {"pinned": True}) is None


def test_workspace_child_counts(db: Session) -> None:
    uid = _user(db)
    seed = _paper(db, "Seed")
    p1 = _paper(db, "P1")
    repo.create_workspace(db, _ws(uid, seed))
    repo.add_workspace_paper(db, WorkspacePaper(workspace_id="ws_1", paper_id=p1, added_by=AddedBy.MANUAL), owner_id=uid)
    counts = repo.workspace_child_counts(db, "ws_1")
    assert counts["papers"] == 2
    assert counts["edges"] == 0
    assert counts["gaps"] == 0 and counts["directions"] == 0


def test_accept_reject_workspace_edge_is_scoped_to_the_workspace(db: Session) -> None:
    uid = _user(db)
    seed = _paper(db, "Seed")
    tgt = _paper(db, "Target")
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed))
    repo.save_trail_edges(
        db,
        "run_1",
        [
            TrailEdge(
                edge_id="edge_1",
                run_id="run_1",
                source_paper_id=seed,
                target_paper_id=tgt,
                relationship_type=RelationshipType.SIMILAR,
                detection_method=DetectionMethod.RULE,
                evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote="q"), role="similarity_signal")],
                confidence=Confidence.MEDIUM,
            )
        ],
    )
    repo.create_workspace(db, _ws(uid, seed, run_id="run_1"))
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_1", owner_id=uid)

    assert repo.accept_reject_workspace_edge(db, "ws_other", uid, "edge_1", UserState.ACCEPTED) is None
    updated = repo.accept_reject_workspace_edge(db, "ws_1", uid, "edge_1", UserState.REJECTED)
    assert updated is not None and updated.user_state == "rejected"
    # rejection is visible to the Phase 7 suppression query
    assert repo.get_rejected_trail_keys(db, "run_1") == {(tgt, "SIMILAR")}
