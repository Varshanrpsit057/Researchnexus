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
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.user import LlmProvider
from app.domain.workspace import (
    AddedBy,
    Grounding,
    ResearchWorkspace,
    WorkspacePaper,
    WorkspacePaperRole,
)
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.retrieval.workspace_index import FaissWorkspaceIndex
from app.services.normalize.canonical import title_hash
from app.services.rag.pipeline import RagRequest, answer_question, build_answer_claims


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


def _paper(db: Session, title: str, chunk_texts: list[str]) -> str:
    pid = repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title)))
    repo.save_chunks(
        db,
        [
            PaperChunk(
                chunk_id=f"chk_{pid}_{i}",
                paper_id=pid,
                section="Results",
                page=i + 2,
                char_start=i * 200,
                char_end=i * 200 + len(t),
                kind=ChunkKind.BODY,
                text=t,
                token_count=len(t.split()),
            )
            for i, t in enumerate(chunk_texts)
        ],
    )
    return pid


@pytest.fixture()
def workspace(db: Session) -> ResearchWorkspace:
    p1 = _paper(db, "Dense Retrieval", ["Dense retrieval improves recall on open domain question answering."])
    p2 = _paper(db, "Reranking", ["Cross encoder reranking raises precision of retrieved passages."])
    return ResearchWorkspace(
        workspace_id="ws_1",
        owner_id="usr_1",
        title="RAG",
        seed_paper_id=p1,
        seed_profile_id="prof_1",
        papers=[
            WorkspacePaper(workspace_id="ws_1", paper_id=p1, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED, grounding=Grounding.FULL_TEXT),
            WorkspacePaper(workspace_id="ws_1", paper_id=p2, added_by=AddedBy.TRAIL),
        ],
    )


def _chunk_ids(db: Session, paper_id: str) -> list[str]:
    return [c.chunk_id for c in repo.get_chunks_for_paper(db, paper_id)]


def _session(stage_payloads: dict[str, object]) -> LlmSession:
    """`stage_payloads` maps a substring of the system prompt to the JSON the
    LLM should return for that stage (contextual filter / generate / verify)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        for needle, payload in stage_payloads.items():
            if needle in body:
                content = payload if isinstance(payload, str) else json.dumps(payload)
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 12, "completion_tokens": 8}},
                )
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x",
        model="m",
        provider=LlmProvider.GROQ,
    )


def _index(db: Session, ws: ResearchWorkspace, settings: Settings) -> FaissWorkspaceIndex:
    idx = FaissWorkspaceIndex(db, workspace_id=ws.workspace_id, index_dir=settings.data_dir / "wi")
    idx.rebuild([p.paper_id for p in ws.papers])
    return idx


def _run(db: Session, ws: ResearchWorkspace, settings: Settings, session: LlmSession | None, query: str, **kw: object):
    return asyncio.run(
        answer_question(
            db,
            workspace=ws,
            request=RagRequest(query=query, scope_paper_ids=kw.get("scope")),  # type: ignore[arg-type]
            session=session,
            settings=settings,
            index=_index(db, ws, settings),
        )
    )


def _payloads(db: Session, ws: ResearchWorkspace, *, supported: list[int]) -> dict[str, object]:
    c1 = _chunk_ids(db, ws.papers[0].paper_id)[0]
    c2 = _chunk_ids(db, ws.papers[1].paper_id)[0]
    return {
        "copy VERBATIM": {  # contextual filter
            "chunks": [
                {"chunk_id": c1, "relevant_text": "Dense retrieval improves recall on open domain question answering."},
                {"chunk_id": c2, "relevant_text": "Cross encoder reranking raises precision of retrieved passages."},
            ]
        },
        "per-sentence": {  # generate (see _SYSTEM in generate.py -> "per-sentence chunk tags" not present; use a stable phrase)
        },
        "ONLY the numbered CONTEXT": {  # generate
            "sentences": [
                {"text": "Dense retrieval improves recall.", "chunk_ids": [c1]},
                {"text": "Reranking raises precision of retrieved passages.", "chunk_ids": [c2]},
            ]
        },
        "fully supports the statement": {  # verify
            "results": [{"index": 0, "supported": 0 in supported}, {"index": 1, "supported": 1 in supported}]
        },
    }


def test_happy_path_answer_is_grounded_and_faithful(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ws = workspace
    session = _session(_payloads(db, ws, supported=[0, 1]))
    ans = _run(db, ws, settings, session, "How is retrieval quality improved?")

    assert ans.answerable is True
    assert len(ans.sentences) == 2
    assert all(s.is_supported and s.chunk_ids for s in ans.sentences)
    assert ans.faithfulness is not None and ans.faithfulness_passed is True
    assert ans.unsupported_dropped == 0
    retrieved = set(_chunk_ids(db, ws.papers[0].paper_id) + _chunk_ids(db, ws.papers[1].paper_id))
    assert set(ans.used_chunk_ids) <= retrieved
    assert ans.completion_tokens > 0

    claims = build_answer_claims(
        ans, workspace_id="ws_1", message_id="cm_1", retrieved_chunk_ids=retrieved,
        chunk_to_paper={c: ws.papers[0].paper_id for c in _chunk_ids(db, ws.papers[0].paper_id)}
        | {c: ws.papers[1].paper_id for c in _chunk_ids(db, ws.papers[1].paper_id)},
    )
    assert len(claims) == 2
    assert all(c.supporting_chunk_ids and c.supporting_paper_ids for c in claims)


def test_unsupported_sentence_is_dropped_and_counted(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ws = workspace
    session = _session(_payloads(db, ws, supported=[0]))  # sentence 1 not supported
    ans = _run(db, ws, settings, session, "How is retrieval quality improved?")

    assert [s.text for s in ans.sentences] == ["Dense retrieval improves recall."]
    assert ans.unsupported_dropped == 1
    assert all(s.chunk_ids for s in ans.sentences)  # Data Model invariant


def test_answerability_gate_skips_generation_when_evidence_is_thin(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ws = workspace
    c1 = _chunk_ids(db, ws.papers[0].paper_id)[0]
    # filter keeps only ONE chunk -> below a workspace bar of 2 relevant chunks
    session = _session({"copy VERBATIM": {"chunks": [{"chunk_id": c1, "relevant_text": "Dense retrieval improves recall on open domain question answering."}]}})
    two = settings.model_copy(update={"rag_min_answerable_chunks": 2})
    ans = _run(db, ws, two, session, "What optimiser learning rate was used for pretraining?")

    assert ans.answerable is False
    assert ans.suggestion and ans.suggestion.startswith("Not enough in this workspace")
    # generation never ran: token totals equal exactly the one upstream
    # contextual-filter call (12/8), nothing added for generate/verify
    assert (ans.prompt_tokens, ans.completion_tokens) == (12, 8)
    assert ans.sentences == [] and "generation_failed" not in ans.warnings


def test_faithfulness_failure_triggers_one_regeneration(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ws = workspace
    c1 = _chunk_ids(db, ws.papers[0].paper_id)[0]
    c2 = _chunk_ids(db, ws.papers[1].paper_id)[0]
    filt = {
        "chunks": [
            {"chunk_id": c1, "relevant_text": "Dense retrieval improves recall on open domain question answering."},
            {"chunk_id": c2, "relevant_text": "Cross encoder reranking raises precision of retrieved passages."},
        ]
    }
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "copy VERBATIM" in body:
            payload: object = filt
        elif "ONLY the numbered CONTEXT" in body:
            calls["n"] += 1
            if calls["n"] == 1:
                payload = {"sentences": [{"text": "Quantum entanglement teleports gradient tensors across galaxies.", "chunk_ids": [c1]}]}
            else:
                payload = {"sentences": [{"text": "Dense retrieval improves recall.", "chunk_ids": [c1]}]}
        elif "fully supports the statement" in body:
            payload = {"results": [{"index": 0, "supported": True}]}
        else:
            payload = {}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 5}})

    session = LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="m", provider=LlmProvider.GROQ,
    )
    ans = _run(db, ws, settings, session, "How is retrieval quality improved?")
    assert ans.regenerated is True
    assert calls["n"] == 2
    assert [s.text for s in ans.sentences] == ["Dense retrieval improves recall."]


def test_generation_failure_is_surfaced_as_a_warning(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ws = workspace
    session = _session({**_payloads(db, ws, supported=[]), "ONLY the numbered CONTEXT": "totally not json"})
    ans = _run(db, ws, settings, session, "How is retrieval quality improved?")
    assert ans.answerable is True
    assert ans.sentences == []
    assert "generation_failed" in ans.warnings


def test_no_session_degrades_without_raising(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ans = _run(db, workspace, settings, None, "How is retrieval quality improved?")
    # filter degrades to keep-all, so it is "answerable", but generation needs a key
    assert ans.answerable is True
    assert ans.sentences == []
    assert "generation_failed" in ans.warnings


def test_scope_restricts_retrieval_to_named_papers(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ws = workspace
    p1 = ws.papers[0].paper_id
    c1 = _chunk_ids(db, p1)[0]
    session = _session({
        "copy VERBATIM": {"chunks": [{"chunk_id": c1, "relevant_text": "Dense retrieval improves recall on open domain question answering."}]},
        "ONLY the numbered CONTEXT": {"sentences": [{"text": "Dense retrieval improves recall.", "chunk_ids": [c1]}]},
        "fully supports the statement": {"results": [{"index": 0, "supported": True}]},
    })
    ans = asyncio.run(
        answer_question(
            db, workspace=ws, request=RagRequest(query="retrieval recall", scope_paper_ids=[p1]),
            session=session, settings=settings, index=_index(db, ws, settings),
        )
    )
    # only p1 chunks may appear
    assert set(ans.used_chunk_ids) <= set(_chunk_ids(db, p1))


def test_pipeline_is_deterministic(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ws = workspace
    payloads = _payloads(db, ws, supported=[0, 1])
    a = _run(db, ws, settings, _session(payloads), "How is retrieval quality improved?")
    b = _run(db, ws, settings, _session(payloads), "How is retrieval quality improved?")
    assert a.model_dump() == b.model_dump()


# --- remediation Phase 2: what a turn that can't be answered really says ----


def _scripted(handler) -> LlmSession:  # noqa: ANN001
    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="m", provider=LlmProvider.GROQ,
    )


def _reply(payload: object) -> httpx.Response:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})


def test_one_relevant_passage_is_enough_to_answer(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    ws = workspace
    c1 = _chunk_ids(db, ws.papers[0].paper_id)[0]
    session = _session(
        {
            "copy VERBATIM": {"chunks": [{"chunk_id": c1, "relevant_text": "Dense retrieval improves recall on open domain question answering."}]},
            "ONLY the numbered CONTEXT": {"sentences": [{"text": "Dense retrieval improves recall.", "chunk_ids": [c1]}]},
            "fully supports the statement": {"results": [{"index": 0, "supported": True}]},
        }
    )
    ans = _run(db, ws, settings, session, "What does dense retrieval improve?")
    assert ans.answerable is True and [s.text for s in ans.sentences] == ["Dense retrieval improves recall."]


def test_the_model_finding_nothing_that_answers_is_not_answerable_not_an_empty_answer(
    db: Session, workspace: ResearchWorkspace, settings: Settings
) -> None:
    ws = workspace
    session = _session({**_payloads(db, ws, supported=[0, 1]), "ONLY the numbered CONTEXT": {"sentences": []}})
    ans = _run(db, ws, settings, session, "What learning rate did pretraining use?")
    assert ans.answerable is False and ans.suggestion and ans.suggestion.startswith("Not enough in this workspace")
    assert ans.warnings == ["not_answerable"]


def test_a_provider_failure_is_raised_with_its_kind_not_reported_as_a_bad_answer(
    db: Session, workspace: ResearchWorkspace, settings: Settings
) -> None:
    from app.llm.client import LlmErrorKind, LlmProviderError

    session = _scripted(lambda r: httpx.Response(401, json={"error": {"message": "Authentication Fails"}}))
    with pytest.raises(LlmProviderError) as info:
        _run(db, workspace, settings, session, "How is retrieval quality improved?")
    assert info.value.kind is LlmErrorKind.AUTH


def test_a_verifier_reply_that_cannot_be_used_is_not_a_verdict(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    session = _session({**_payloads(db, workspace, supported=[0, 1]), "fully supports the statement": "I think they are all fine"})
    ans = _run(db, workspace, settings, session, "How is retrieval quality improved?")
    assert ans.sentences == [] and "verification_failed" in ans.warnings


def test_a_reply_that_is_not_the_json_asked_for_gets_one_repair(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    payloads = _payloads(db, workspace, supported=[0, 1])
    generations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        text = request.content.decode()
        if "ONLY the numbered CONTEXT" in text:
            generations.append(text)
            # first: prose around a broken object; the repair: the object
            return _reply("Here you go: {sentences: oops" if len(generations) == 1 else payloads["ONLY the numbered CONTEXT"])
        for needle, payload in payloads.items():
            if needle in text:
                return _reply(payload)
        return _reply({})

    ans = _run(db, workspace, settings, _scripted(handler), "How is retrieval quality improved?")
    assert len(generations) == 2 and "That reply could not be used" in generations[1]
    assert len(ans.sentences) == 2 and ans.warnings == []


def test_a_rewrite_that_hits_a_provider_error_keeps_the_first_answer(db: Session, workspace: ResearchWorkspace, settings: Settings) -> None:
    c1 = _chunk_ids(db, workspace.papers[0].paper_id)[0]
    payloads = _payloads(db, workspace, supported=[0])
    generations = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        text = request.content.decode()
        if "ONLY the numbered CONTEXT" in text:
            generations["n"] += 1
            if generations["n"] == 1:  # supported, but far from its source: the gate asks for a rewrite
                return _reply({"sentences": [{"text": "Quantum entanglement teleports gradient tensors across galaxies.", "chunk_ids": [c1]}]})
            return httpx.Response(503, json={"error": {"message": "Server overloaded"}})
        if "fully supports the statement" in text:
            return _reply({"results": [{"index": 0, "supported": True}]})
        return _reply(payloads["copy VERBATIM"])

    ans = _run(db, workspace, settings, _scripted(handler), "How is retrieval quality improved?")
    assert [s.text for s in ans.sentences] == ["Quantum entanglement teleports gradient tensors across galaxies."]
    assert ans.regenerated is False and "faithfulness_below_threshold" in ans.warnings
