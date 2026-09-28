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
from app.domain.usage import LlmCall
from app.domain.user import LlmProvider
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.llm.client import ChatMessage, ChatResult, LlmErrorKind, LlmProviderError
from app.llm.usage import MeteredClient, usage_scope
from app.services.gaps.pipeline import GapBuildResult
from app.services.normalize.canonical import title_hash
from app.services.orchestrator.orchestrator import ResearchOrchestrator
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


def _workspace(db: Session) -> ResearchWorkspace:
    uid = "usr_1"
    repo.create_user(db, user_id=uid, email="u@example.com")
    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    db.query(PaperORM).filter_by(id=seed).update({"has_full_text": True, "abstract": "an abstract"})
    db.commit()
    ws = ResearchWorkspace(
        workspace_id="ws_1", owner_id=uid, title="W", seed_paper_id=seed, seed_profile_id="prof",
        papers=[WorkspacePaper(workspace_id="ws_1", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
    )
    repo.create_workspace(db, ws)
    return repo.get_workspace(db, "ws_1", uid)  # type: ignore[return-value]


def _orch(db: Session, settings: Settings) -> ResearchOrchestrator:
    return ResearchOrchestrator(db=db, settings=settings)


class _Model:
    """A provider that answers every call with the same usage."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def chat(self, **kw: object) -> ChatResult:
        if self.fail:
            raise LlmProviderError("rate limited", kind=LlmErrorKind.RATE_LIMITED, provider="deepseek")
        return ChatResult(content="ok", latency_ms=1, prompt_tokens=300, completion_tokens=40, cached_prompt_tokens=100)

    async def structured(self, **kw: object) -> object:
        raise NotImplementedError

    async def probe_capabilities(self, **kw: object) -> object:
        raise NotImplementedError


def _metered(ledger: list[LlmCall], *, fail: bool = False) -> MeteredClient:
    return MeteredClient(_Model(fail=fail), owner_id="usr_1", provider=LlmProvider.DEEPSEEK, recorder=ledger.append)  # type: ignore[arg-type]


PING = [ChatMessage(role="user", content="q")]


# --- every stage keeps the tokens its model calls really used (remediation Phase 5)


def test_a_stage_run_keeps_the_tokens_its_calls_used_and_labels_them_with_the_stage(db: Session, settings: Settings) -> None:
    ws = _workspace(db)
    orch = _orch(db, settings)
    ledger: list[LlmCall] = []
    model = _metered(ledger)

    async def answer(**kw: object) -> RagAnswer:
        for _ in range(2):
            await model.chat(api_key="k", model="deepseek-flash", messages=PING)
        # the stage's own figure is ignored: the ledger's calls are the truth
        return RagAnswer(answerable=True, text="ok", prompt_tokens=1, completion_tokens=1)

    asyncio.run(orch.run_rag_stage(workspace=ws, request=RagRequest(query="q"), session=None, owner_id=ws.owner_id, answer_fn=answer))

    [run] = repo.list_stage_runs(db, "ws_1")
    assert (run.ok, run.tokens_prompt, run.tokens_completion) == (True, 600, 80)
    assert {(c.feature, c.workspace_id) for c in ledger} == {("rag", "ws_1")}


def test_a_failed_stage_still_keeps_the_tokens_it_spent(db: Session, settings: Settings) -> None:
    ws = _workspace(db)
    orch = _orch(db, settings)
    ledger: list[LlmCall] = []
    model, failing = _metered(ledger), _metered(ledger, fail=True)

    async def answer(**kw: object) -> RagAnswer:
        await model.chat(api_key="k", model="m", messages=PING)
        await failing.chat(api_key="k", model="m", messages=PING)
        raise AssertionError("unreachable")

    with pytest.raises(LlmProviderError):
        asyncio.run(orch.run_rag_stage(workspace=ws, request=RagRequest(query="q"), session=None, owner_id=ws.owner_id, answer_fn=answer))
    [run] = repo.list_stage_runs(db, "ws_1")
    assert (run.ok, run.tokens_prompt, run.tokens_completion) == (False, 300, 40)
    assert [c.ok for c in ledger] == [True, False]


def test_a_stage_inside_named_work_keeps_the_callers_name(db: Session, settings: Settings) -> None:
    ws = _workspace(db)
    orch = _orch(db, settings)
    ledger: list[LlmCall] = []
    model = _metered(ledger)

    async def build(**kw: object) -> GapBuildResult:
        await model.chat(api_key="k", model="m", messages=PING)
        return GapBuildResult(workspace_id="ws_1", gap_count=0)

    async def run() -> None:
        with usage_scope("gaps", workspace_id="ws_1", job_id="job_7"):
            await orch.run_gaps_stage(workspace=ws, session=None, owner_id=ws.owner_id, job_id="job_7", build_fn=build)

    asyncio.run(run())
    assert [(c.feature, c.job_id) for c in ledger] == [("gaps", "job_7")]
    assert repo.list_stage_runs(db, "ws_1", stage=StageName.GAPS)[0].tokens_prompt == 300


def test_a_stage_that_calls_no_model_records_no_tokens(db: Session, settings: Settings) -> None:
    ws = _workspace(db)
    orch = _orch(db, settings)
    asyncio.run(orch.run_citations_stage(workspace=ws, paper_ids=None, formats=["apa"], owner_id=ws.owner_id))
    [run] = repo.list_stage_runs(db, "ws_1", stage=StageName.CITATIONS)
    assert (run.tokens_prompt, run.tokens_completion) == (0, 0)


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


def test_directions_stage_wraps_build_directions_and_logs_a_stage_run(db: Session, settings: Settings) -> None:
    from app.services.directions.pipeline import DirectionBuildResult

    ws = _workspace(db)
    orch = _orch(db, settings)

    async def fake_build_directions(**kw: object) -> DirectionBuildResult:
        return DirectionBuildResult(workspace_id="ws_1")

    asyncio.run(
        orch.run_directions_stage(workspace=ws, gap_ids=["gap_1"], session=None, owner_id=ws.owner_id, build_fn=fake_build_directions)
    )
    [run] = repo.list_stage_runs(db, "ws_1", stage=StageName.DIRECTIONS)
    assert run.ok is True


def test_citations_stage_wraps_build_citations(db: Session, settings: Settings) -> None:
    ws = _workspace(db)
    orch = _orch(db, settings)

    result = asyncio.run(orch.run_citations_stage(workspace=ws, paper_ids=None, formats=["apa"], owner_id=ws.owner_id))
    assert result.citations
    rows = repo.list_stage_runs(db, "ws_1", stage=StageName.CITATIONS)
    assert len(rows) == 1
