from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperRelationshipORM, WorkspacePaperORM
from app.domain.candidate import NormalizedCandidate, SearchRun
from app.domain.comparison import Comparison, ComparisonSchema
from app.domain.direction import ResearchDirection
from app.domain.gap import GapEvidence, GapType, ResearchGap
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


# --- one run imported into several workspaces (migration 0014) --------------


def _run_with_edge(db: Session, *, state: UserState = UserState.PENDING) -> tuple[str, str]:
    uid = _user(db)
    seed = _paper(db, "Seed")
    tgt = _paper(db, "Target")
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed))
    edge = TrailEdge(
        edge_id="edge_1",
        run_id="run_1",
        source_paper_id=seed,
        target_paper_id=tgt,
        relationship_type=RelationshipType.SIMILAR,
        detection_method=DetectionMethod.RULE,
        evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote="q"), role="target_claim")],
        confidence=Confidence.MEDIUM,
    )
    edge.user_state = state.value
    repo.save_trail_edges(db, "run_1", [edge])
    repo.create_workspace(db, _ws(uid, seed, wid="ws_1", run_id="run_1"))
    repo.create_workspace(db, _ws(uid, seed, wid="ws_2", run_id="run_1"))
    return uid, seed


def test_a_second_workspace_gets_its_own_unreviewed_copy_and_the_first_keeps_its_edge(db: Session) -> None:
    uid, _ = _run_with_edge(db)
    assert repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_1", owner_id=uid) == 1
    repo.accept_reject_workspace_edge(db, "ws_1", uid, "edge_1", UserState.ACCEPTED)

    assert repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_2", owner_id=uid) == 1

    [first] = repo.get_workspace_trail_edges(db, "ws_1")
    [second] = repo.get_workspace_trail_edges(db, "ws_2")
    assert first.edge_id == "edge_1" and first.user_state == "accepted"  # not moved, not reset
    assert second.edge_id != "edge_1" and second.user_state == "pending"
    assert second.evidence == first.evidence and second.relationship_type == first.relationship_type
    row = db.get(PaperRelationshipORM, second.edge_id)
    assert row is not None and row.copied_from == "edge_1"


def test_attaching_a_run_twice_to_the_same_workspace_adds_nothing(db: Session) -> None:
    uid, _ = _run_with_edge(db)
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_1", owner_id=uid)
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_2", owner_id=uid)
    assert repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_1", owner_id=uid) == 0
    assert repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_2", owner_id=uid) == 0
    assert db.query(PaperRelationshipORM).count() == 2


def test_run_scoped_reads_see_the_runs_own_trail_not_workspace_copies(db: Session) -> None:
    uid, _ = _run_with_edge(db)
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_1", owner_id=uid)
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_2", owner_id=uid)
    [copy] = repo.get_workspace_trail_edges(db, "ws_2")
    repo.accept_reject_workspace_edge(db, "ws_2", uid, copy.edge_id, UserState.REJECTED)

    assert [e.edge_id for e in repo.get_trail_edges(db, "run_1")] == ["edge_1"]
    # a rejection in one workspace's copy does not stop the run proposing the edge
    assert repo.get_rejected_trail_keys(db, "run_1") == set()


def test_rebuilding_a_runs_trail_keeps_its_edges_in_their_workspaces(db: Session) -> None:
    uid, seed = _run_with_edge(db)
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_1", owner_id=uid)
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_2", owner_id=uid)
    repo.accept_reject_workspace_edge(db, "ws_1", uid, "edge_1", UserState.ACCEPTED)

    # the trail pipeline re-saves the run (its edges come back with no workspace)
    rebuilt = repo.get_trail_edges(db, "run_1")[0].model_copy(update={"workspace_id": None, "rule_fired": "rebuilt"})
    repo.save_trail_edges(db, "run_1", [rebuilt])

    [first] = repo.get_workspace_trail_edges(db, "ws_1")
    assert first.edge_id == "edge_1" and first.rule_fired == "rebuilt" and first.user_state == "accepted"
    assert len(repo.get_workspace_trail_edges(db, "ws_2")) == 1  # the copy is left alone


def test_deleting_a_workspace_drops_its_copies_and_releases_its_primaries_unreviewed(db: Session) -> None:
    uid, _ = _run_with_edge(db)
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_1", owner_id=uid)
    repo.attach_run_edges_to_workspace(db, run_id="run_1", workspace_id="ws_2", owner_id=uid)
    repo.accept_reject_workspace_edge(db, "ws_1", uid, "edge_1", UserState.REJECTED)
    [copy] = repo.get_workspace_trail_edges(db, "ws_2")

    assert repo.delete_workspace(db, "ws_2", uid) is True
    assert db.get(PaperRelationshipORM, copy.edge_id) is None
    assert [e.user_state for e in repo.get_workspace_trail_edges(db, "ws_1")] == ["rejected"]

    assert repo.delete_workspace(db, "ws_1", uid) is True
    primary = db.get(PaperRelationshipORM, "edge_1")
    assert primary is not None and primary.workspace_id is None and primary.user_state == "pending"


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


def test_workspace_child_counts_reflect_real_gaps_directions_and_comparisons(db: Session) -> None:
    # Found live: counts hard-coded gaps/directions to 0 ("arrive in Phases
    # 11 / 12") long after both shipped, so the API reported zero for every
    # workspace. Rejected items are excluded, matching how edges are counted.
    uid = _user(db)
    seed = _paper(db, "Seed")
    repo.create_workspace(db, _ws(uid, seed))
    evidence = [GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="q"))]

    def gap(gid: str, state: str) -> ResearchGap:
        return ResearchGap(
            gap_id=gid, workspace_id="ws_1", statement=gid, gap_type=GapType.METHOD_GAP,
            supporting_papers=["p1", "p2"], supporting_evidence=evidence,
            confidence=Confidence.MEDIUM, self_support_passed=True, user_state=state,
        )

    repo.save_gaps(db, "ws_1", [gap("gap_1", "accepted"), gap("gap_2", "candidate"), gap("gap_3", "rejected")], owner_id=uid)
    repo.save_directions(
        db,
        "ws_1",
        [
            ResearchDirection(
                direction_id=did, workspace_id="ws_1", gap_id="gap_1", proposal="Apply X.", motivation="m",
                supporting_evidence=evidence, related_papers=["p1", "p2"], suggested_method="X",
                evaluation_strategy="e", risks=[], kind="evidence_backed_inference", critique={},
                confidence=Confidence.MEDIUM, confidence_basis={}, user_state=state,
            )
            for did, state in (("dir_1", "candidate"), ("dir_2", "rejected"))
        ],
        owner_id=uid,
    )
    repo.save_comparison(
        db,
        Comparison(
            comparison_id="cmp_1", workspace_id="ws_1",
            column_schema=ComparisonSchema(columns=["method"], generated_by="deterministic_union"),
            paper_ids=["p1"], rows=[], coverage=0.0,
        ),
        owner_id=uid,
    )

    counts = repo.workspace_child_counts(db, "ws_1")
    assert counts["gaps"] == 2
    assert counts["directions"] == 1
    assert counts["comparisons"] == 1


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
