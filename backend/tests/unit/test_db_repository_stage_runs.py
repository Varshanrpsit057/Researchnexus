from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import StageRunORM
from app.domain.candidate import NormalizedCandidate
from app.domain.orchestrator import StageName, StageRun
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


def _run(*, run_id: str = "sr_1", owner_id: str = "usr_1", workspace_id: str | None = "ws_1", stage: StageName = StageName.RAG, ok: bool = True) -> StageRun:
    return StageRun(
        id=run_id, owner_id=owner_id, workspace_id=workspace_id, stage=stage, tool="answer_question",
        input_hash="in", output_hash="out", latency_ms=5, ok=ok,
    )


def test_record_and_list_stage_runs_round_trip(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.record_stage_run(db, _run(workspace_id=wid, owner_id=uid))
    runs = repo.list_stage_runs(db, wid)
    assert len(runs) == 1
    assert runs[0].stage == StageName.RAG
    assert runs[0].ok is True


def test_list_stage_runs_is_newest_first(db: Session) -> None:
    wid, uid = _workspace(db)
    r1 = _run(run_id="sr_1", workspace_id=wid, owner_id=uid)
    r2 = _run(run_id="sr_2", workspace_id=wid, owner_id=uid)
    repo.record_stage_run(db, r1)
    repo.record_stage_run(db, r2)
    runs = repo.list_stage_runs(db, wid)
    assert [r.id for r in runs] == ["sr_2", "sr_1"]


def test_list_stage_runs_can_filter_by_stage(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.record_stage_run(db, _run(run_id="sr_1", workspace_id=wid, owner_id=uid, stage=StageName.RAG))
    repo.record_stage_run(db, _run(run_id="sr_2", workspace_id=wid, owner_id=uid, stage=StageName.GAPS))
    assert [r.id for r in repo.list_stage_runs(db, wid, stage=StageName.GAPS)] == ["sr_2"]


def test_list_stage_runs_respects_limit(db: Session) -> None:
    wid, uid = _workspace(db)
    for i in range(5):
        repo.record_stage_run(db, _run(run_id=f"sr_{i}", workspace_id=wid, owner_id=uid))
    assert len(repo.list_stage_runs(db, wid, limit=2)) == 2


def _second_workspace(db: Session) -> str:
    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed2", title_hash=title_hash("Seed2")))
    repo.create_workspace(
        db,
        ResearchWorkspace(
            workspace_id="ws_other", owner_id="usr_1", title="W2", seed_paper_id=seed, seed_profile_id="prof2",
            papers=[WorkspacePaper(workspace_id="ws_other", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
        ),
    )
    return "ws_other"


def test_list_stage_runs_is_scoped_to_the_workspace(db: Session) -> None:
    wid, uid = _workspace(db)
    other_wid = _second_workspace(db)
    repo.record_stage_run(db, _run(run_id="sr_1", workspace_id=wid, owner_id=uid))
    repo.record_stage_run(db, _run(run_id="sr_2", workspace_id=other_wid, owner_id=uid))
    assert [r.id for r in repo.list_stage_runs(db, wid)] == ["sr_1"]


def test_pre_workspace_stage_runs_have_no_workspace_id(db: Session) -> None:
    _wid, uid = _workspace(db)
    repo.record_stage_run(db, _run(run_id="sr_pre", workspace_id=None, owner_id=uid, stage=StageName.INGEST))
    row = db.get(StageRunORM, "sr_pre")
    assert row is not None and row.workspace_id is None


def test_a_failed_stage_run_records_the_error(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.record_stage_run(db, _run(run_id="sr_1", workspace_id=wid, owner_id=uid, ok=False))
    run = repo.list_stage_runs(db, wid)[0]
    assert run.ok is False


def test_deleting_a_workspace_cascades_to_its_stage_runs(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.record_stage_run(db, _run(workspace_id=wid, owner_id=uid))
    repo.delete_workspace(db, wid, uid)
    assert db.query(StageRunORM).filter_by(workspace_id=wid).count() == 0
