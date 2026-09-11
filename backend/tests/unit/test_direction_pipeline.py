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
from app.domain.candidate import NormalizedCandidate
from app.domain.gap import GapEvidence, GapType, GapUserState, ResearchGap
from app.domain.profile import Confidence, SourceSpan
from app.domain.user import LlmProvider
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.directions.pipeline import build_directions
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


def _gap(gid: str = "gap_1") -> ResearchGap:
    return ResearchGap(
        gap_id=gid, workspace_id="ws_1",
        statement="No workspace paper applies contrastive pretraining to dense retrieval.",
        gap_type=GapType.METHOD_GAP, supporting_papers=["p1", "p2"],
        supporting_evidence=[
            GapEvidence(paper_id="p1", span=SourceSpan(paper_id="p1", quote="we study dense retrieval")),
            GapEvidence(paper_id="p2", span=SourceSpan(paper_id="p2", quote="we also study dense retrieval")),
        ],
        why_unaddressed="The papers study dense retrieval but none adopt contrastive pretraining.",
        proposed_direction="Apply contrastive pretraining to the shared setting.",
        affected_methods=["contrastive pretraining"],
        confidence=Confidence.MEDIUM, self_support_passed=True,
    )


@pytest.fixture()
def workspace(db: Session) -> ResearchWorkspace:
    repo.create_user(db, user_id="usr_1", email="u@e.com")
    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    ws = ResearchWorkspace(
        workspace_id="ws_1", owner_id="usr_1", title="W", seed_paper_id=seed, seed_profile_id="prof",
        papers=[WorkspacePaper(workspace_id="ws_1", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
    )
    repo.create_workspace(db, ws)
    repo.save_gaps(db, "ws_1", [_gap("gap_accepted"), _gap("gap_candidate")], owner_id="usr_1")
    repo.set_gap_user_state(db, "gap_accepted", workspace_id="ws_1", owner_id="usr_1", state=GapUserState.ACCEPTED)
    return ws


def _session(*, grounded: bool = True) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "next-step research directions" in body:
            if grounded:
                payload: object = {"directions": [
                    {"proposal": "Apply contrastive pretraining to dense retrieval.", "motivation": "The papers study dense retrieval but skip contrastive pretraining.", "suggested_method": "contrastive pretraining", "possible_dataset": None, "evaluation_strategy": "Evaluate on the shared setting.", "risks": ["May not help."]},
                ]}
            else:
                payload = {"directions": [
                    {"proposal": "Apply quantum annealing to dense retrieval.", "motivation": "Quantum annealing already solves this reliably.", "suggested_method": "quantum annealing", "possible_dataset": None, "evaluation_strategy": "Evaluate.", "risks": []},
                ]}
        elif "Rate the DIRECTION" in body:
            payload = {"novelty": 3, "specificity": 4, "feasibility": 2, "groundedness": 5}
        else:
            payload = {}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 4, "completion_tokens": 2}})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="groq/x", provider=LlmProvider.GROQ,
    )


def _run(db, ws, settings, session, gap_ids):
    return asyncio.run(build_directions(db, workspace=ws, gap_ids=gap_ids, session=session, settings=settings))


def test_direction_is_generated_only_for_an_accepted_gap(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, _session(), ["gap_accepted", "gap_candidate", "gap_ghost"])
    assert res.direction_count == 1
    assert res.skipped_not_accepted == 1  # gap_candidate
    assert res.skipped_not_found == 1     # gap_ghost

    directions = repo.get_directions(db, "ws_1")
    assert len(directions) == 1
    d = directions[0]
    assert d.gap_id == "gap_accepted"
    assert d.supporting_evidence  # inherited from the gap
    assert d.related_papers == ["p1", "p2"]
    assert d.kind == "evidence_backed_inference"
    assert d.confidence in {Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW}
    assert d.user_state == "candidate"


def test_unsupported_llm_output_is_dropped_not_persisted(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, _session(grounded=False), ["gap_accepted"])
    assert res.direction_count == 0
    assert res.dropped_unsupported == 1
    assert repo.get_directions(db, "ws_1") == []


def test_rerun_is_deterministic(db, workspace, settings) -> None:
    _run(db, workspace, settings, _session(), ["gap_accepted"])
    first = [d.model_dump(exclude={"generated_at"}) for d in repo.get_directions(db, "ws_1")]
    _run(db, workspace, settings, _session(), ["gap_accepted"])
    second = [d.model_dump(exclude={"generated_at"}) for d in repo.get_directions(db, "ws_1")]
    assert first == second


def test_no_session_yields_exactly_one_template_direction_per_gap(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, None, ["gap_accepted"])
    assert res.direction_count == 1
    d = repo.get_directions(db, "ws_1")[0]
    assert d.generator_model is None
    assert d.kind == "evidence_backed_inference"
