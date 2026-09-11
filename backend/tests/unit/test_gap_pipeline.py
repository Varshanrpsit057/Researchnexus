from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM
from app.domain.gap import GapType, GapUserState
from app.domain.profile import Confidence, ProfileField, ProfileList, ResearchProfile, SourceSpan
from app.domain.user import LlmProvider
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.gaps.pipeline import GapBuildOptions, build_gaps
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


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, database_url="sqlite://")  # type: ignore[call-arg]


def _paper(db: Session, pid: str, *, year: int, **facets: list[str]) -> None:
    db.add(PaperORM(id=pid, title=pid.upper(), title_hash=title_hash(pid), year=year))
    db.commit()
    kw: dict = {
        "profile_id": f"prof_{pid}", "paper_id": pid, "title": pid.upper(), "abstract": "ab",
        "domain": ProfileField(value="IR"),
        "research_problem": ProfileField(
            value=facets.get("problem", ["retrieval"])[0],
            source_span=SourceSpan(paper_id=pid, section="Intro", char_start=1, char_end=9, quote=facets.get("problem", ["retrieval"])[0]),
        ),
    }
    for key, attr in (("methods", "methods"), ("datasets", "datasets"), ("limitations", "limitations")):
        vals = facets.get(key, [])
        if vals:
            kw[attr] = ProfileList(items=[
                ProfileField(value=v, source_span=SourceSpan(paper_id=pid, section="Body", char_start=10, char_end=20, quote=v))
                for v in vals
            ])
    repo.upsert_profile(db, ResearchProfile(**kw))


@pytest.fixture()
def workspace(db: Session) -> ResearchWorkspace:
    repo.create_user(db, user_id="usr_1", email="u@e.com")
    _paper(db, "p1", year=2022, problem=["dense retrieval"], methods=["bm25"], limitations=["English only"])
    _paper(db, "p2", year=2022, problem=["dense retrieval"], methods=["tf-idf"], limitations=["English only"])
    _paper(db, "p3", year=2022, problem=["dense retrieval"], methods=["contrastive pretraining"])
    ws = ResearchWorkspace(
        workspace_id="ws_1", owner_id="usr_1", title="W", seed_paper_id="p1", seed_profile_id="prof_p1",
        papers=[
            WorkspacePaper(workspace_id="ws_1", paper_id="p1", added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED),
            WorkspacePaper(workspace_id="ws_1", paper_id="p2", added_by=AddedBy.TRAIL),
            WorkspacePaper(workspace_id="ws_1", paper_id="p3", added_by=AddedBy.TRAIL),
        ],
    )
    repo.create_workspace(db, ws)
    return ws


def _session(*, articulate_ok: bool = True, self_support: bool = True) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "phrase a research gap" in body:
            if not articulate_ok:
                payload: object = {"statement": "The papers ignore quantum annealing.", "why_unaddressed": "quantum annealing untried", "proposed_direction": "use quantum annealing"}
            elif "limitation" in body and "English only" in body:
                payload = {
                    "statement": "Two papers report the same English only limitation and none of them resolves it.",
                    "why_unaddressed": "The English only limitation is stated but not addressed.",
                    "proposed_direction": "Extend the setting beyond English only.",
                }
            elif "contrastive pretraining" in body:
                payload = {
                    "statement": "No workspace paper applies contrastive pretraining to dense retrieval.",
                    "why_unaddressed": "The papers study dense retrieval but none adopt contrastive pretraining.",
                    "proposed_direction": "Apply contrastive pretraining to the shared setting.",
                }
            else:
                # phrase strictly from the facts/evidence terms the pipeline sent
                payload = {"statement": "The workspace papers share no common value on this facet.", "why_unaddressed": "Each paper differs on it.", "proposed_direction": "Adopt a shared choice."}
        elif "fully supports the statement" in body:
            payload = {"results": [{"index": 0, "supported": self_support}]}
        else:
            payload = {}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="groq/x", provider=LlmProvider.GROQ,
    )


def _run(db, ws, settings, session, **kw):
    return asyncio.run(build_gaps(db, workspace=ws, options=GapBuildOptions(**kw), session=session, settings=settings))


def test_pipeline_surfaces_evidence_grounded_gaps(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, _session())
    assert res.gap_count >= 1
    gaps = repo.get_gaps(db, "ws_1")
    assert all(len(g.supporting_papers) >= 2 for g in gaps)
    assert all(g.supporting_evidence and all(e.span.quote for e in g.supporting_evidence) for g in gaps)
    assert all(g.self_support_passed for g in gaps)
    assert all(g.user_state == GapUserState.CANDIDATE.value for g in gaps)
    assert all(g.confidence in {Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW} for g in gaps)
    # a shared "English only" limitation across p1+p2 -> GENERALIZATION_GAP
    assert GapType.GENERALIZATION_GAP in {g.gap_type for g in gaps}


def test_articulation_that_invents_a_claim_is_dropped(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, _session(articulate_ok=False))
    assert res.gap_count == 0
    assert res.dropped_unsupported_articulation >= 1
    assert repo.get_gaps(db, "ws_1") == []


def test_self_support_failure_drops_the_candidate(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, _session(self_support=False))
    assert res.gap_count == 0
    assert res.dropped_self_support >= 1


def test_no_session_yields_no_gaps_because_self_support_cannot_pass(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, None)
    assert res.gap_count == 0
    assert res.dropped_self_support >= 1


def test_rerun_is_deterministic(db, workspace, settings) -> None:
    a = _run(db, workspace, settings, _session())
    first = [g.model_dump(exclude={"generated_at"}) for g in repo.get_gaps(db, "ws_1")]
    b = _run(db, workspace, settings, _session())
    second = [g.model_dump(exclude={"generated_at"}) for g in repo.get_gaps(db, "ws_1")]
    assert a.gap_count == b.gap_count
    assert first == second


def test_rejected_gap_is_not_reproposed_on_rerun(db, workspace, settings) -> None:
    _run(db, workspace, settings, _session())
    gaps = repo.get_gaps(db, "ws_1")
    victim = gaps[0]
    repo.set_gap_user_state(db, victim.gap_id, workspace_id="ws_1", owner_id="usr_1", state=GapUserState.REJECTED)

    res = _run(db, workspace, settings, _session())
    assert res.skipped_rejected >= 1
    surviving = repo.get_gaps(db, "ws_1")
    assert victim.gap_id in {g.gap_id for g in surviving}
    assert next(g for g in surviving if g.gap_id == victim.gap_id).user_state == "rejected"


def test_gap_types_filter_limits_the_pipeline(db, workspace, settings) -> None:
    _run(db, workspace, settings, _session(), gap_types={GapType.GENERALIZATION_GAP})
    assert {g.gap_type for g in repo.get_gaps(db, "ws_1")} <= {GapType.GENERALIZATION_GAP}
