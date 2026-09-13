from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM
from app.domain.candidate import NormalizedCandidate
from app.domain.orchestrator import StageName
from app.domain.rag import RagAnswer
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.services.gaps.pipeline import GapBuildResult
from app.services.normalize.canonical import title_hash
from app.services.orchestrator.orchestrator import BudgetBlocked, ResearchOrchestrator
from app.services.rag.pipeline import RagRequest


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
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _workspace(db: Session, *, budget: float = 5.0, used: float = 0.0) -> ResearchWorkspace:
    uid = "usr_1"
    repo.create_user(db, user_id=uid, email="u@example.com")
    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    db.query(PaperORM).filter_by(id=seed).update({"has_full_text": True, "abstract": "an abstract"})
    db.commit()
    ws = ResearchWorkspace(
        workspace_id="ws_1", owner_id=uid, title="W", seed_paper_id=seed, seed_profile_id="prof",
        papers=[WorkspacePaper(workspace_id="ws_1", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
        token_budget_usd=budget,
    )
    repo.create_workspace(db, ws)
    if used:
        repo.add_workspace_spend(db, "ws_1", uid, tokens_prompt=0, tokens_completion=0, cost_usd=used)
    return repo.get_workspace(db, "ws_1", uid)  # type: ignore[return-value]


def _orch(db: Session, settings: Settings) -> ResearchOrchestrator:
    return ResearchOrchestrator(db=db, settings=settings)


# --- RAG stage: budget allow / degrade / block ------------------------------


def test_rag_stage_allows_and_records_spend_when_well_under_budget(db: Session, settings: Settings) -> None:
    ws = _workspace(db, budget=5.0, used=0.0)
    orch = _orch(db, settings)

    async def fake_answer(**kw: object) -> RagAnswer:
        return RagAnswer(answerable=True, text="ok", prompt_tokens=500, completion_tokens=500)

    result = asyncio.run(
        orch.run_rag_stage(
            workspace=ws, request=RagRequest(query="what dataset?"), session=None,
            owner_id=ws.owner_id, answer_fn=fake_answer,
        )
    )
    assert result.text == "ok"
    updated = repo.get_workspace(db, "ws_1", ws.owner_id)
    assert updated is not None and updated.cost_used_usd > 0.0

    rows = repo.list_stage_runs(db, "ws_1")
    assert len(rows) == 1 and rows[0].ok is True and rows[0].tokens_prompt == 500


def test_rag_stage_degrades_k_once_past_the_threshold(db: Session, settings: Settings) -> None:
    ws = _workspace(db, budget=5.0, used=4.5)  # 90% spent, threshold is 80%
    orch = _orch(db, settings)
    seen_k: dict[str, int] = {}

    async def fake_answer(**kw: object) -> RagAnswer:
        call_settings = kw["settings"]
        assert isinstance(call_settings, Settings)
        seen_k["k"] = call_settings.rag_retrieve_k
        return RagAnswer(answerable=True, text="ok")

    asyncio.run(
        orch.run_rag_stage(
            workspace=ws, request=RagRequest(query="q"), session=None, owner_id=ws.owner_id, answer_fn=fake_answer,
        )
    )
    assert seen_k["k"] < settings.rag_retrieve_k


def test_rag_stage_blocks_and_never_calls_answer_question_once_the_cap_is_reached(
    db: Session, settings: Settings
) -> None:
    ws = _workspace(db, budget=5.0, used=5.0)
    orch = _orch(db, settings)
    called = {"n": 0}

    async def fake_answer(**kw: object) -> RagAnswer:
        called["n"] += 1
        return RagAnswer(answerable=True, text="should not happen")

    with pytest.raises(BudgetBlocked):
        asyncio.run(
            orch.run_rag_stage(
                workspace=ws, request=RagRequest(query="q"), session=None, owner_id=ws.owner_id, answer_fn=fake_answer,
            )
        )
    assert called["n"] == 0

    rows = repo.list_stage_runs(db, "ws_1")
    assert len(rows) == 1 and rows[0].ok is False and rows[0].error == "budget_blocked"


# --- gaps / directions / comparison / citations stage wrappers --------------


def test_gaps_stage_wraps_build_gaps_and_logs_a_stage_run(db: Session, settings: Settings) -> None:
    ws = _workspace(db)
    orch = _orch(db, settings)

    async def fake_build_gaps(**kw: object) -> GapBuildResult:
        return GapBuildResult(workspace_id="ws_1", gap_count=0)

    result = asyncio.run(orch.run_gaps_stage(workspace=ws, session=None, owner_id=ws.owner_id, build_fn=fake_build_gaps))
    assert result.gap_count == 0
    rows = repo.list_stage_runs(db, "ws_1", stage=StageName.GAPS)
    assert len(rows) == 1 and rows[0].ok is True


def test_directions_stage_wraps_build_directions_and_records_spend(db: Session, settings: Settings) -> None:
    from app.services.directions.pipeline import DirectionBuildResult

    ws = _workspace(db)
    orch = _orch(db, settings)

    async def fake_build_directions(**kw: object) -> DirectionBuildResult:
        return DirectionBuildResult(workspace_id="ws_1", prompt_tokens=100, completion_tokens=50)

    asyncio.run(
        orch.run_directions_stage(workspace=ws, gap_ids=["gap_1"], session=None, owner_id=ws.owner_id, build_fn=fake_build_directions)
    )
    updated = repo.get_workspace(db, "ws_1", ws.owner_id)
    assert updated is not None and updated.cost_used_usd > 0.0


def test_citations_stage_wraps_build_citations(db: Session, settings: Settings) -> None:
    ws = _workspace(db)
    orch = _orch(db, settings)

    result = asyncio.run(orch.run_citations_stage(workspace=ws, paper_ids=None, formats=["apa"], owner_id=ws.owner_id))
    assert result.citations
    rows = repo.list_stage_runs(db, "ws_1", stage=StageName.CITATIONS)
    assert len(rows) == 1
