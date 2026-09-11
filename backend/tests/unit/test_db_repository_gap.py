from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import ResearchGapORM
from app.domain.candidate import NormalizedCandidate
from app.domain.gap import EvidenceRole, GapEvidence, GapType, GapUserState, ResearchGap
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
    return "ws_1", "usr_1"


def _gap(gid: str, *, gap_type: GapType = GapType.METHOD_GAP, state: str = "candidate") -> ResearchGap:
    return ResearchGap(
        gap_id=gid, workspace_id="ws_1",
        statement="No paper does X.", gap_type=gap_type,
        supporting_papers=["p1", "p2"],
        supporting_evidence=[
            GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", section="Body", char_start=1, char_end=5, quote="q1")),
            GapEvidence(paper_id="p2", span=SourceSpan(paper_id="p2", section="Body", char_start=1, char_end=5, quote="q2")),
        ],
        conflicting_evidence=[GapEvidence(paper_id="p2", span=SourceSpan(paper_id="p2", quote="c"), role=EvidenceRole.CONFLICTS_WITH_GAP.value)],
        evidence_coverage=1.0, confidence=Confidence.MEDIUM,
        confidence_basis={"n_supporting": 2, "self_support": True},
        detection_rule="method_coverage", self_support_passed=True, user_state=state,
        generator_model="groq/x",
    )


def test_save_and_get_gaps_round_trip(db: Session) -> None:
    _workspace(db)
    repo.save_gaps(db, "ws_1", [_gap("gap_1")], owner_id="usr_1")
    got = repo.get_gaps(db, "ws_1")
    assert len(got) == 1
    g = got[0]
    assert g.gap_type is GapType.METHOD_GAP
    assert [e.paper_id for e in g.supporting_evidence] == ["p1", "p2"]
    assert g.conflicting_evidence[0].role == "conflicts_with_gap"
    assert g.confidence is Confidence.MEDIUM and g.confidence_basis["n_supporting"] == 2
    assert g.self_support_passed is True and g.user_state == "candidate"


def test_get_gaps_filters_by_state_and_is_workspace_scoped(db: Session) -> None:
    _workspace(db)
    repo.save_gaps(db, "ws_1", [_gap("gap_1"), _gap("gap_2")], owner_id="usr_1")
    repo.set_gap_user_state(db, "gap_1", workspace_id="ws_1", owner_id="usr_1", state=GapUserState.ACCEPTED)
    assert {g.gap_id for g in repo.get_gaps(db, "ws_1", state="accepted")} == {"gap_1"}
    assert {g.gap_id for g in repo.get_gaps(db, "ws_1", state="candidate")} == {"gap_2"}
    assert repo.get_gap(db, "gap_1", workspace_id="ws_other") is None


def test_rerun_keeps_accepted_and_rejected_rows_and_drops_stale_candidates(db: Session) -> None:
    _workspace(db)
    repo.save_gaps(db, "ws_1", [_gap("gap_keep"), _gap("gap_stale"), _gap("gap_reject")], owner_id="usr_1")
    repo.set_gap_user_state(db, "gap_keep", workspace_id="ws_1", owner_id="usr_1", state=GapUserState.ACCEPTED)
    repo.set_gap_user_state(db, "gap_reject", workspace_id="ws_1", owner_id="usr_1", state=GapUserState.REJECTED)

    # a rerun that only re-produces gap_keep
    repo.save_gaps(db, "ws_1", [_gap("gap_keep", state="candidate")], owner_id="usr_1")
    ids_states = {g.gap_id: g.user_state for g in repo.get_gaps(db, "ws_1")}
    assert ids_states == {"gap_keep": "accepted", "gap_reject": "rejected"}  # stale candidate gone


def test_get_rejected_gap_ids(db: Session) -> None:
    _workspace(db)
    repo.save_gaps(db, "ws_1", [_gap("gap_1"), _gap("gap_2")], owner_id="usr_1")
    repo.set_gap_user_state(db, "gap_2", workspace_id="ws_1", owner_id="usr_1", state=GapUserState.REJECTED)
    assert repo.get_rejected_gap_ids(db, "ws_1") == {"gap_2"}


def test_set_gap_user_state_is_tenant_scoped(db: Session) -> None:
    _workspace(db)
    repo.save_gaps(db, "ws_1", [_gap("gap_1")], owner_id="usr_1")
    assert repo.set_gap_user_state(db, "gap_1", workspace_id="ws_other", owner_id="usr_1", state=GapUserState.ACCEPTED) is None
    assert repo.set_gap_user_state(db, "gap_1", workspace_id="ws_1", owner_id="intruder", state=GapUserState.ACCEPTED) is None
    ok = repo.set_gap_user_state(db, "gap_1", workspace_id="ws_1", owner_id="usr_1", state=GapUserState.ACCEPTED)
    assert ok is not None and ok.user_state == "accepted"


def test_deleting_a_workspace_cascades_to_gaps(db: Session) -> None:
    _workspace(db)
    repo.save_gaps(db, "ws_1", [_gap("gap_1")], owner_id="usr_1")
    repo.delete_workspace(db, "ws_1", "usr_1")
    assert db.query(ResearchGapORM).filter_by(workspace_id="ws_1").count() == 0
