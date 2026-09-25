"""The research chat's stream, persistence and history (Phase 9 frontend).

Runs the real RAG pipeline end to end through the real OpenAI-compatible
client; only the provider's HTTP endpoint is a mock transport (no BYOK key
exists in tests), reusing test_chat_synthesis_api's fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import repository as repo
from app.db.session import get_session_factory
from app.domain.citation import ArtefactKind, Claim
from tests.integration.test_chat_synthesis_api import (
    _h,
    _make_client,
    _mock_llm,
    _rag_router,
    _save_key,
    _seed_workspace,
    _token,
)

TWO_SENTENCES = {
    "sentences": [
        {"text": "Dense retrieval improves recall.", "chunk_ids": ["chk_seed_0"]},
        {"text": "Reranking raises precision of passages.", "chunk_ids": ["chk_p2_0"]},
    ]
}
BOTH_SUPPORTED = {"results": [{"index": 0, "supported": True}, {"index": 1, "supported": True}]}
QUESTION = "How is retrieval quality improved?"


def _events(stream: str) -> list[tuple[str, dict]]:
    out = []
    for block in stream.strip().split("\n\n"):
        name = next(ln[len("event: "):] for ln in block.splitlines() if ln.startswith("event: "))
        data = next(ln[len("data: "):] for ln in block.splitlines() if ln.startswith("data: "))
        out.append((name, json.loads(data)))
    return out


def _ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, router: object = None) -> tuple[TestClient, str, str]:
    client = _make_client(tmp_path)
    token = _token(client)
    wid = _seed_workspace(client, token)
    _save_key(client, token, monkeypatch)
    _mock_llm(monkeypatch, router or _rag_router(generate=TWO_SENTENCES, verify=BOTH_SUPPORTED))
    return client, token, wid


def _ask(client: TestClient, token: str, wid: str, **body: object) -> list[tuple[str, dict]]:
    r = client.post(
        f"/api/v1/workspaces/{wid}/chat",
        json={"message": QUESTION, **body},
        headers={**_h(token), "Accept": "text/event-stream"},
    )
    assert r.status_code == 200, r.text
    return _events(r.text)


def test_the_stream_reports_each_stage_then_places_every_citation_after_its_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token, wid = _ready(tmp_path, monkeypatch)
    events = _ask(client, token, wid)

    names = [n for n, _ in events]
    stages = [d["stage"] for n, d in events if n == "status"]
    assert stages == ["searching", "reading", "writing", "checking"]
    assert names.index("token") > names.index("status")
    # sentence one's words, its citation, sentence two's words, its citation
    text, order = "", []
    for name, data in events:
        if name == "token":
            text += data["text"]
        elif name == "citation":
            order.append((text.strip(), data["marker"], data["sources"][0]["chunk_id"]))
    assert order == [
        ("Dense retrieval improves recall.", "[1]", "chk_seed_0"),
        ("Dense retrieval improves recall. Reranking raises precision of passages.", "[2]", "chk_p2_0"),
    ]
    first = next(d for n, d in events if n == "citation")
    source = first["sources"][0]
    assert first["sentence"] == "Dense retrieval improves recall."
    assert (source["paper_title"], source["section"], source["page"]) == ("Dense Retrieval", "Results", 3)
    assert source["quote"] == "Dense retrieval improves recall on question answering."
    assert names[-2:] == ["usage", "done"]


def test_a_reloaded_conversation_keeps_its_evidence_and_outcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, token, wid = _ready(tmp_path, monkeypatch)
    done = _ask(client, token, wid)[-1][1]

    hist = client.get(f"/api/v1/workspaces/{wid}/chat/sessions/{done['session_id']}", headers=_h(token)).json()
    user, assistant = hist["messages"]
    assert (user["role"], user["content"]) == ("user", QUESTION)
    assert assistant["message_id"] == done["message_id"]
    assert [c["sentence"] for c in assistant["claims"]] == ["Dense retrieval improves recall.", "Reranking raises precision of passages."]
    reranking = assistant["claims"][1]["sources"][0]
    assert (reranking["paper_title"], reranking["section"], reranking["page"]) == ("Reranking", "Method", 2)
    assert assistant["unsupported_dropped"] == 0 and assistant["suggestion"] is None

    sessions = client.get(f"/api/v1/workspaces/{wid}/chat/sessions", headers=_h(token)).json()["sessions"]
    assert [(s["session_id"], s["questions"]) for s in sessions] == [(done["session_id"], 1)]
    assert sessions[0]["last_active_at"]


def test_an_unanswerable_question_keeps_its_suggestion_after_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    router = _rag_router(
        generate={"sentences": []},
        verify={"results": []},
        filt={"chunks": [{"chunk_id": "chk_seed_0", "relevant_text": "Dense retrieval improves recall on question answering."}]},
    )
    client, token, wid = _ready(tmp_path, monkeypatch, router)
    events = _ask(client, token, wid, message="What learning rate did pretraining use?")
    done = events[-1][1]
    assert done["answerable"] is False and done["suggestion"]
    assert not any(n in ("token", "citation") for n, _ in events)

    hist = client.get(f"/api/v1/workspaces/{wid}/chat/sessions/{done['session_id']}", headers=_h(token)).json()
    assistant = hist["messages"][1]
    assert assistant["answerable"] is False and assistant["suggestion"] == done["suggestion"]
    assert "not_answerable" in assistant["warnings"]


def test_a_provider_failure_leaves_nothing_behind_so_a_retry_cannot_duplicate_the_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable sk-secret-looking-text")

    client, token, wid = _ready(tmp_path, monkeypatch, down)
    events = _ask(client, token, wid)
    name, data = events[-1]
    # every RAG stage absorbs provider errors, so an outage surfaces as "no usable answer"
    assert name == "error" and data["code"] == "generation_failed"
    assert "sk-secret" not in data["message"]  # the provider's raw reply is never echoed
    assert client.get(f"/api/v1/workspaces/{wid}/chat/sessions", headers=_h(token)).json()["sessions"] == []

    plain = client.post(f"/api/v1/workspaces/{wid}/chat", json={"message": QUESTION}, headers=_h(token))
    assert plain.status_code == 502 and plain.json()["detail"]["error"]["code"] == "generation_failed"

    # the provider recovers: one question, one answer
    _mock_llm(monkeypatch, _rag_router(generate=TWO_SENTENCES, verify=BOTH_SUPPORTED))
    done = _ask(client, token, wid)[-1][1]
    hist = client.get(f"/api/v1/workspaces/{wid}/chat/sessions/{done['session_id']}", headers=_h(token)).json()
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant"]


def test_regenerating_replaces_the_last_answer_and_keeps_the_question_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, token, wid = _ready(tmp_path, monkeypatch)
    first = _ask(client, token, wid)[-1][1]
    sid = first["session_id"]

    again = _ask(client, token, wid, message="", session_id=sid, regenerate=True)[-1][1]
    assert again["session_id"] == sid
    assert again["replaced_message_ids"] == [first["message_id"]]
    hist = client.get(f"/api/v1/workspaces/{wid}/chat/sessions/{sid}", headers=_h(token)).json()
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant"]
    assert hist["messages"][1]["message_id"] == again["message_id"] != first["message_id"]
    db = get_session_factory()()
    try:
        assert repo.get_claims_for_artefact(db, first["message_id"]) == []  # the old answer's claims went with it
    finally:
        db.close()


def test_regenerate_and_empty_questions_are_refused_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, token, wid = _ready(tmp_path, monkeypatch)
    url = f"/api/v1/workspaces/{wid}/chat"
    assert client.post(url, json={"message": "   "}, headers=_h(token)).json()["detail"]["error"]["code"] == "empty_message"
    no_session = client.post(url, json={"regenerate": True}, headers=_h(token))
    assert no_session.status_code == 422 and no_session.json()["detail"]["error"]["code"] == "session_required"
    ghost = client.post(url, json={"regenerate": True, "session_id": "cs_ghost"}, headers=_h(token))
    assert ghost.status_code == 404


def test_claims_come_back_in_sentence_order_past_ten_sentences(tmp_path: Path) -> None:
    _make_client(tmp_path)
    db = get_session_factory()()
    try:
        from app.db.models import PaperORM, WorkspaceORM
        from app.services.normalize.canonical import title_hash

        repo.create_user(db, user_id="usr_1", email="u@example.com")
        repo.save_paper(db, PaperORM(id="pap_1", title="P", title_hash=title_hash("p"), has_full_text=True))
        db.add(WorkspaceORM(id="ws_1", owner_id="usr_1", title="W", seed_paper_id="pap_1", seed_profile_id="prof"))
        db.commit()
        claims = [
            Claim(
                claim_id=f"clm_cm_1_{i}", workspace_id="ws_1", artefact_kind=ArtefactKind.ANSWER.value,
                artefact_id="cm_1", sentence=f"sentence {i}", supporting_chunk_ids=["chk"],
            )
            for i in range(12)
        ]
        repo.save_claims(db, list(reversed(claims)))
        assert [c.sentence for c in repo.get_claims_for_artefact(db, "cm_1")] == [f"sentence {i}" for i in range(12)]
    finally:
        db.close()
