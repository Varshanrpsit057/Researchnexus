from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import ResearchDirectionORM
from app.domain.candidate import NormalizedCandidate
from app.domain.direction import DirectionUserState, ResearchDirection
from app.domain.gap import GapEvidence, GapType, GapUserState, ResearchGap
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
    repo.create_user(db, user_id="usr_1", email="u@e.com")
    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="S", title_hash=title_hash("S")))
    repo.create_workspace(
        db,
        ResearchWorkspace(
            workspace_id="ws_1", owner_id="usr_1", title="W", seed_paper_id=seed, seed_profile_id="prof",
            papers=[WorkspacePaper(workspace_id="ws_1", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
        ),
    )
    gap = ResearchGap(
        gap_id="gap_1", workspace_id="ws_1", statement="s", gap_type=GapType.METHOD_GAP,
        supporting_papers=["p1", "p2"],
        supporting_evidence=[GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="q"))],
        confidence=Confidence.MEDIUM, self_support_passed=True, user_state="accepted",
    )
    repo.save_gaps(db, "ws_1", [gap], owner_id="usr_1")
    return "ws_1", "usr_1"


def _direction(did: str, *, gap_id: str = "gap_1", state: str = "candidate") -> ResearchDirection:
    return ResearchDirection(
        direction_id=did, workspace_id="ws_1", gap_id=gap_id,
        proposal="Apply X.", motivation="The gap shows X is missing.",
        supporting_evidence=[GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="q1"))],
        related_papers=["p1", "p2"], suggested_method="X", evaluation_strategy="Evaluate.",
        risks=["r1"], kind="evidence_backed_inference",
        critique={"novelty": 3, "specificity": 3, "feasibility": 2, "groundedness": 4},
        confidence=Confidence.MEDIUM, confidence_basis={"kind": "evidence_backed_inference"},
        user_state=state, generator_model="groq/x",
    )


def test_save_and_get_directions_round_trip(db: Session) -> None:
    _workspace(db)
    repo.save_directions(db, "ws_1", [_direction("dir_1")], owner_id="usr_1")
    got = repo.get_directions(db, "ws_1")
    assert len(got) == 1
    d = got[0]
    assert d.gap_id == "gap_1"
    assert d.supporting_evidence[0].span.quote == "q1"
    assert d.kind == "evidence_backed_inference"
    assert d.critique["groundedness"] == 4
    assert d.confidence is Confidence.MEDIUM
    assert d.user_state == "candidate"


def test_get_directions_filters_by_state_and_gap_and_is_workspace_scoped(db: Session) -> None:
    _workspace(db)
    repo.save_directions(db, "ws_1", [_direction("dir_1"), _direction("dir_2")], owner_id="usr_1")
    repo.set_direction_user_state(db, "dir_1", workspace_id="ws_1", owner_id="usr_1", state=DirectionUserState.ACCEPTED)
    assert {d.direction_id for d in repo.get_directions(db, "ws_1", state="accepted")} == {"dir_1"}
    assert {d.direction_id for d in repo.get_directions(db, "ws_1", gap_id="gap_1")} == {"dir_1", "dir_2"}
    assert repo.get_direction(db, "dir_1", workspace_id="ws_other") is None


def test_rerun_keeps_accepted_and_rejected_and_drops_stale_candidates(db: Session) -> None:
    _workspace(db)
    repo.save_directions(db, "ws_1", [_direction("dir_keep"), _direction("dir_stale"), _direction("dir_reject")], owner_id="usr_1")
    repo.set_direction_user_state(db, "dir_keep", workspace_id="ws_1", owner_id="usr_1", state=DirectionUserState.ACCEPTED)
    repo.set_direction_user_state(db, "dir_reject", workspace_id="ws_1", owner_id="usr_1", state=DirectionUserState.REJECTED)

    repo.save_directions(db, "ws_1", [_direction("dir_keep")], owner_id="usr_1")
    states = {d.direction_id: d.user_state for d in repo.get_directions(db, "ws_1")}
    assert states == {"dir_keep": "accepted", "dir_reject": "rejected"}


def test_set_direction_user_state_is_tenant_scoped(db: Session) -> None:
    _workspace(db)
    repo.save_directions(db, "ws_1", [_direction("dir_1")], owner_id="usr_1")
    assert repo.set_direction_user_state(db, "dir_1", workspace_id="ws_other", owner_id="usr_1", state=DirectionUserState.ACCEPTED) is None
    assert repo.set_direction_user_state(db, "dir_1", workspace_id="ws_1", owner_id="intruder", state=DirectionUserState.ACCEPTED) is None
    ok = repo.set_direction_user_state(db, "dir_1", workspace_id="ws_1", owner_id="usr_1", state=DirectionUserState.ACCEPTED)
    assert ok is not None and ok.user_state == "accepted"


def test_deleting_the_gap_cascades_to_its_directions(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.save_directions(db, "ws_1", [_direction("dir_1")], owner_id="usr_1")
    db.delete(db.query(repo.ResearchGapORM).filter_by(id="gap_1").one())
    db.commit()
    assert db.query(ResearchDirectionORM).filter_by(gap_id="gap_1").count() == 0


def test_deleting_the_workspace_cascades_to_directions(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.save_directions(db, "ws_1", [_direction("dir_1")], owner_id="usr_1")
    repo.delete_workspace(db, "ws_1", "usr_1")
    assert db.query(ResearchDirectionORM).filter_by(workspace_id="ws_1").count() == 0


def test_saving_one_gaps_directions_leaves_another_gaps_candidates_alone(db: Session) -> None:
    _workspace(db)
    other = repo.get_gap(db, "gap_1", workspace_id="ws_1")
    assert other is not None
    repo.save_gaps(db, "ws_1", [other, other.model_copy(update={"gap_id": "gap_2"})], owner_id="usr_1")
    repo.save_directions(db, "ws_1", [_direction("dir_a")], owner_id="usr_1", gap_ids=["gap_1"])

    # directions are generated per chosen gap: a run for gap_2 must not wipe gap_1's unreviewed ones
    repo.save_directions(db, "ws_1", [_direction("dir_b", gap_id="gap_2")], owner_id="usr_1", gap_ids=["gap_2"])
    assert {d.direction_id for d in repo.get_directions(db, "ws_1")} == {"dir_a", "dir_b"}

    # a rerun for gap_1 still replaces gap_1's own stale candidates
    repo.save_directions(db, "ws_1", [_direction("dir_a2")], owner_id="usr_1", gap_ids=["gap_1"])
    assert {d.direction_id for d in repo.get_directions(db, "ws_1")} == {"dir_a2", "dir_b"}


def test_a_gap_rerun_keeps_a_gap_that_directions_rest_on(db: Session) -> None:
    _workspace(db)
    repo.save_directions(db, "ws_1", [_direction("dir_1")], owner_id="usr_1")
    repo.set_direction_user_state(db, "dir_1", workspace_id="ws_1", owner_id="usr_1", state=DirectionUserState.ACCEPTED)
    # the reader moves the gap back to review, then a rerun no longer finds it
    repo.set_gap_user_state(db, "gap_1", workspace_id="ws_1", owner_id="usr_1", state=GapUserState.CANDIDATE)
    repo.save_gaps(db, "ws_1", [], owner_id="usr_1")

    assert repo.get_gap(db, "gap_1", workspace_id="ws_1") is not None
    kept = repo.get_directions(db, "ws_1")
    assert [(d.direction_id, d.user_state) for d in kept] == [("dir_1", "accepted")]
