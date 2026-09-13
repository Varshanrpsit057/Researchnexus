from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.domain.orchestrator import StageName
from app.services.orchestrator.orchestrator import ResearchOrchestrator


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


@pytest.fixture()
def settings() -> Settings:
    return Settings(_env_file=None, orchestrator_max_stage_attempts=2)  # type: ignore[call-arg]


@pytest.fixture()
def owner_id(db: Session) -> str:
    repo.create_user(db, user_id="usr_1", email="u@example.com")
    return "usr_1"


def _orch(db: Session, settings: Settings) -> ResearchOrchestrator:
    return ResearchOrchestrator(db=db, settings=settings)


def test_a_successful_sync_stage_returns_its_result_and_logs_a_row(db: Session, settings: Settings, owner_id: str) -> None:
    orch = _orch(db, settings)

    async def go() -> str:
        return await orch.run_stage(
            StageName.INGEST, "fake_tool", orch.sync_call(lambda: "ok"), owner_id=owner_id, input_for_hash={"x": 1},
        )

    result = asyncio.run(go())
    assert result == "ok"
    from app.db.models import StageRunORM

    rows = db.query(StageRunORM).all()
    assert len(rows) == 1
    assert rows[0].ok is True
    assert rows[0].stage == "ingest"
    assert rows[0].tool == "fake_tool"
    assert rows[0].error is None


def test_a_successful_async_stage_works_the_same_way(db: Session, settings: Settings, owner_id: str) -> None:
    orch = _orch(db, settings)

    async def fake_async() -> str:
        return "async-ok"

    async def go() -> str:
        return await orch.run_stage(StageName.RAG, "fake_async_tool", fake_async, owner_id=owner_id)

    assert asyncio.run(go()) == "async-ok"


def test_a_failing_stage_logs_the_error_and_reraises(db: Session, settings: Settings, owner_id: str) -> None:
    orch = _orch(db, settings)

    async def boom() -> None:
        raise ValueError("kaboom")

    async def go() -> None:
        await orch.run_stage(StageName.RANKING, "fake_tool", boom, owner_id=owner_id, max_attempts=1)

    with pytest.raises(ValueError):
        asyncio.run(go())

    from app.db.models import StageRunORM

    rows = db.query(StageRunORM).all()
    assert len(rows) == 1
    assert rows[0].ok is False
    assert "kaboom" in (rows[0].error or "")


def test_retry_succeeds_on_the_second_attempt_and_logs_both_attempts(db: Session, settings: Settings, owner_id: str) -> None:
    orch = _orch(db, settings)
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("transient")
        return "recovered"

    async def go() -> str:
        return await orch.run_stage(StageName.DISCOVERY, "flaky_tool", flaky, owner_id=owner_id, max_attempts=2)

    result = asyncio.run(go())
    assert result == "recovered"
    assert calls["n"] == 2

    from app.db.models import StageRunORM

    rows = db.query(StageRunORM).order_by(StageRunORM.ts).all()
    assert len(rows) == 2
    assert rows[0].ok is False
    assert rows[1].ok is True


def test_max_attempts_is_capped_regardless_of_what_the_caller_requests(db: Session, settings: Settings, owner_id: str) -> None:
    # settings.orchestrator_max_stage_attempts=2 (fixture); requesting 100 must not mean 100 tries.
    orch = _orch(db, settings)
    calls = {"n": 0}

    async def always_fails() -> None:
        calls["n"] += 1
        raise RuntimeError("nope")

    async def go() -> None:
        await orch.run_stage(StageName.TRAIL, "fake_tool", always_fails, owner_id=owner_id, max_attempts=100)

    with pytest.raises(RuntimeError):
        asyncio.run(go())
    assert calls["n"] == 2  # capped at settings.orchestrator_max_stage_attempts, not 100


def test_a_stage_that_exceeds_its_timeout_fails_and_is_logged(db: Session, settings: Settings, owner_id: str) -> None:
    orch = _orch(db, settings)

    async def slow() -> str:
        await asyncio.sleep(0.3)
        return "too slow"

    async def go() -> str:
        return await orch.run_stage(StageName.RAG, "slow_tool", slow, owner_id=owner_id, timeout_s=0.05, max_attempts=1)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(go())

    from app.db.models import StageRunORM

    rows = db.query(StageRunORM).all()
    assert len(rows) == 1
    assert rows[0].ok is False


def test_workspace_and_job_ids_are_recorded_on_the_row(db: Session, settings: Settings, owner_id: str) -> None:
    from app.domain.candidate import NormalizedCandidate
    from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
    from app.services.normalize.canonical import title_hash

    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    repo.create_workspace(
        db,
        ResearchWorkspace(
            workspace_id="ws_1", owner_id=owner_id, title="W", seed_paper_id=seed, seed_profile_id="prof",
            papers=[WorkspacePaper(workspace_id="ws_1", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
        ),
    )
    orch = _orch(db, settings)

    async def ok() -> str:
        return "done"

    async def go() -> str:
        return await orch.run_stage(StageName.GAPS, "fake_tool", ok, owner_id=owner_id, workspace_id="ws_1", job_id="job_1")

    asyncio.run(go())
    runs = repo.list_stage_runs(db, "ws_1")
    assert len(runs) == 1
    assert runs[0].job_id == "job_1"
    assert runs[0].workspace_id == "ws_1"


def test_input_and_output_hashes_are_deterministic_for_equal_values(db: Session, settings: Settings, owner_id: str) -> None:
    orch = _orch(db, settings)

    async def go() -> None:
        await orch.run_stage(
            StageName.INGEST, "t", orch.sync_call(lambda: {"a": 1, "b": 2}),
            owner_id=owner_id, input_for_hash={"same": "input"},
        )
        await orch.run_stage(
            StageName.INGEST, "t", orch.sync_call(lambda: {"a": 1, "b": 2}),
            owner_id=owner_id, input_for_hash={"same": "input"},
        )

    asyncio.run(go())
    from app.db.models import StageRunORM

    rows = db.query(StageRunORM).order_by(StageRunORM.ts).all()
    assert len(rows) == 2
    assert rows[0].input_hash == rows[1].input_hash
    assert rows[0].output_hash == rows[1].output_hash
