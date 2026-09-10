from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import ChatMessageORM, ClaimORM
from app.domain.candidate import NormalizedCandidate
from app.domain.chat import ChatMessage, ChatRole, ChatSession
from app.domain.citation import Citation, Claim
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


def test_chat_session_and_messages_round_trip_and_are_tenant_scoped(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.create_chat_session(db, ChatSession(session_id="cs_1", workspace_id=wid, owner_id=uid, title="Q1"))

    assert repo.get_chat_session(db, "cs_1", workspace_id=wid, owner_id=uid) is not None
    assert repo.get_chat_session(db, "cs_1", workspace_id=wid, owner_id="usr_other") is None
    assert repo.get_chat_session(db, "cs_1", workspace_id="ws_other", owner_id=uid) is None

    repo.add_chat_message(db, ChatMessage(message_id="cm_1", session_id="cs_1", role=ChatRole.USER, content="hi"))
    repo.add_chat_message(
        db,
        ChatMessage(
            message_id="cm_2", session_id="cs_1", role=ChatRole.ASSISTANT, content="answer",
            citations=["clm_cm_2_0"], tokens_prompt=100, tokens_completion=20, faithfulness=0.9,
        ),
    )
    msgs = repo.get_chat_messages(db, "cs_1")
    assert [m.role for m in msgs] == [ChatRole.USER, ChatRole.ASSISTANT]
    assert msgs[1].citations == ["clm_cm_2_0"] and msgs[1].faithfulness == 0.9

    assert [s.session_id for s in repo.list_chat_sessions(db, wid, uid)] == ["cs_1"]
    assert repo.list_chat_sessions(db, wid, "usr_other") == []


def test_deleting_a_session_cascades_to_messages(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.create_chat_session(db, ChatSession(session_id="cs_1", workspace_id=wid, owner_id=uid))
    repo.add_chat_message(db, ChatMessage(message_id="cm_1", session_id="cs_1", role=ChatRole.USER, content="x"))
    db.delete(db.get(repo.ChatSessionORM, "cs_1"))
    db.commit()
    assert db.query(ChatMessageORM).filter_by(session_id="cs_1").count() == 0


def test_save_and_reload_claims_upserts_by_id(db: Session) -> None:
    wid, _ = _workspace(db)
    claims = [
        Claim(claim_id="clm_1", workspace_id=wid, artefact_kind="answer", artefact_id="cm_1", sentence="A.", supporting_chunk_ids=["c1"], supporting_paper_ids=["p1"], is_supported=True),
        Claim(claim_id="clm_2", workspace_id=wid, artefact_kind="answer", artefact_id="cm_1", sentence="B.", supporting_chunk_ids=["c2"], is_supported=False),
    ]
    repo.save_claims(db, claims)
    got = repo.get_claims_for_artefact(db, "cm_1")
    assert [c.claim_id for c in got] == ["clm_1", "clm_2"]
    assert got[0].supporting_paper_ids == ["p1"] and got[0].is_supported is True

    repo.save_claims(db, [Claim(claim_id="clm_1", workspace_id=wid, artefact_kind="answer", artefact_id="cm_1", sentence="A revised.", supporting_chunk_ids=["c1", "c3"], is_supported=True)])
    got = repo.get_claims_for_artefact(db, "cm_1")
    assert len(got) == 2
    assert next(c for c in got if c.claim_id == "clm_1").sentence == "A revised."


def test_deleting_a_workspace_cascades_to_claims_and_citations(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.save_claims(db, [Claim(claim_id="clm_1", workspace_id=wid, artefact_kind="answer", artefact_id="a", sentence="s", supporting_chunk_ids=["c1"])])
    seed = repo.get_workspace(db, wid, uid).seed_paper_id  # type: ignore[union-attr]
    repo.upsert_citation(db, Citation(citation_id="cit_1", workspace_id=wid, paper_id=seed, formatted={"apa": "X"}, resolved_from="arxiv"))

    repo.delete_workspace(db, wid, uid)
    assert db.query(ClaimORM).filter_by(workspace_id=wid).count() == 0
    assert repo.get_citations(db, wid) == []


def test_citation_upsert_is_unique_per_workspace_paper(db: Session) -> None:
    wid, uid = _workspace(db)
    seed = repo.get_workspace(db, wid, uid).seed_paper_id  # type: ignore[union-attr]
    repo.upsert_citation(db, Citation(citation_id="cit_1", workspace_id=wid, paper_id=seed, formatted={"apa": "v1"}, resolved_from="arxiv"), owner_id=uid)
    repo.upsert_citation(db, Citation(citation_id="cit_ignored", workspace_id=wid, paper_id=seed, formatted={"apa": "v2"}, resolved_from="crossref"))
    cits = repo.get_citations(db, wid)
    assert len(cits) == 1
    assert cits[0].formatted["apa"] == "v2" and cits[0].resolved_from == "crossref"
