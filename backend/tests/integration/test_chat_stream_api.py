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
    # times carry their zone, so a browser in any timezone reads them right
    assert sessions[0]["last_active_at"].endswith("+00:00")
    assert sessions[0]["created_at"].endswith(("Z", "+00:00")) and user["created_at"].endswith(("Z", "+00:00"))


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
    # an outage is said as one, naming the provider -- never "no usable answer"
    assert name == "error" and data["code"] == "provider_error" and data["kind"] == "unavailable"
    assert data["message"] == "Groq is unavailable right now. Try again in a moment."
    assert "sk-secret" not in data["message"]  # the provider's raw reply is never echoed
    assert client.get(f"/api/v1/workspaces/{wid}/chat/sessions", headers=_h(token)).json()["sessions"] == []

    plain = client.post(f"/api/v1/workspaces/{wid}/chat", json={"message": QUESTION}, headers=_h(token))
    error = plain.json()["detail"]["error"]
    assert plain.status_code == 502 and error["code"] == "provider_error" and error["kind"] == "unavailable"

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


def test_stage_events_cross_a_real_socket_while_the_model_is_still_working(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Progressive, not buffered: served by a real uvicorn server, the first
    stages reach the client while the provider has not answered yet."""
    import asyncio
    import socket
    import threading
    import time

    import uvicorn

    gate = threading.Event()
    answer = _rag_router(generate=TWO_SENTENCES, verify=BOTH_SUPPORTED)

    async def held(request: httpx.Request) -> httpx.Response:
        while not gate.is_set():  # the model is "thinking" until the test releases it
            await asyncio.sleep(0.02)
        return answer(request)

    client, token, wid = _ready(tmp_path, monkeypatch, held)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    threading.Timer(15, gate.set).start()  # never hang the suite

    try:
        seen: list[str] = []
        released_at_first_status = None
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{port}/api/v1/workspaces/{wid}/chat",
            json={"message": QUESTION},
            headers={**_h(token), "Accept": "text/event-stream"},
            timeout=httpx.Timeout(20.0),
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line.startswith("event: "):
                    continue
                name = line[len("event: "):]
                seen.append(name)
                if name == "status" and released_at_first_status is None:
                    released_at_first_status = gate.is_set()
                    gate.set()  # let the model answer now
        assert released_at_first_status is False  # it arrived before the model said a word
        assert seen[0] == "status" and seen[-1] == "done" and "citation" in seen
    finally:
        gate.set()
        server.should_exit = True
        thread.join(timeout=10)


# --- remediation Phase 2: provider reliability and real usage ---------------


def _owner(email: str = "r@example.com") -> str:
    db = get_session_factory()()
    try:
        user = repo.get_user_by_email(db, email)
        assert user is not None
        return user.id
    finally:
        db.close()


def _calls(owner_id: str, workspace_id: str | None = None) -> list:
    db = get_session_factory()()
    try:
        return repo.list_llm_calls(db, owner_id, workspace_id=workspace_id)
    finally:
        db.close()


def _nothing_saved(client: TestClient, token: str, wid: str) -> bool:
    return client.get(f"/api/v1/workspaces/{wid}/chat/sessions", headers=_h(token)).json()["sessions"] == []


def test_every_call_a_turn_makes_is_recorded_with_its_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, token, wid = _ready(tmp_path, monkeypatch)
    events = _ask(client, token, wid)
    usage = next(d for n, d in events if n == "usage")

    calls = _calls(_owner(), wid)
    # the contextual filter, the answer, the check
    assert [c.feature for c in calls] == ["chat", "chat", "chat"] and all(c.ok for c in calls)
    assert sum(c.prompt_tokens for c in calls) == usage["prompt"] == 90
    assert sum(c.completion_tokens for c in calls) == usage["completion"] == 36
    hist = client.get(f"/api/v1/workspaces/{wid}/chat/sessions/{events[-1][1]['session_id']}", headers=_h(token)).json()
    assert hist["messages"][1]["tokens_prompt"] == 90


def test_an_account_out_of_credit_is_said_plainly_saves_nothing_and_is_still_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broke(_: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "Insufficient Balance", "type": "unknown_error"}})

    client, token, wid = _ready(tmp_path, monkeypatch, broke)
    name, data = _ask(client, token, wid)[-1]
    assert (name, data["code"], data["kind"]) == ("error", "provider_error", "insufficient_balance")
    assert data["message"] == "Your Groq account is out of credit. Top it up, then try again."
    assert _nothing_saved(client, token, wid)
    assert [(c.ok, c.error_kind) for c in _calls(_owner(), wid)] == [(False, "insufficient_balance")]


def test_a_rejected_key_is_named_and_stops_being_the_working_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def rejected(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Authentication Fails, Your api key: ****sk-x is invalid"}})

    client, token, wid = _ready(tmp_path, monkeypatch, rejected)
    name, data = _ask(client, token, wid)[-1]
    assert (data["code"], data["kind"]) == ("provider_error", "auth")
    assert data["message"] == "Groq rejected the saved API key. Check it in Settings, or save a new one."
    keys = client.get("/api/v1/settings/llm-keys", headers=_h(token)).json()
    assert [k["status"] for k in (keys["keys"] if isinstance(keys, dict) else keys)] == ["failed"]
    # the next question doesn't fail the same way again: no key works, and it says so
    again = client.post(f"/api/v1/workspaces/{wid}/chat", json={"message": QUESTION}, headers=_h(token))
    assert again.status_code == 409 and again.json()["detail"]["error"]["code"] == "llm_key_required"


@pytest.mark.parametrize(
    ("verify", "generate", "code"),
    [
        ("they all look fine to me", TWO_SENTENCES, "verification_failed"),
        ({"results": [{"index": 0, "supported": False}, {"index": 1, "supported": False}]}, TWO_SENTENCES, "unsupported_answer"),
        (BOTH_SUPPORTED, "no json here", "generation_failed"),
    ],
)
def test_a_turn_with_no_answer_to_show_is_a_named_failure_and_saves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verify: object, generate: object, code: str
) -> None:
    client, token, wid = _ready(tmp_path, monkeypatch, _rag_router(generate=generate, verify=verify))  # type: ignore[arg-type]
    name, data = _ask(client, token, wid)[-1]
    assert (name, data["code"]) == ("error", code) and data["message"]
    assert _nothing_saved(client, token, wid)
    assert _calls(_owner(), wid)  # what it cost is still counted


def test_a_long_stage_keeps_the_stream_alive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.routers.chat as chat_router

    answer = _rag_router(generate=TWO_SENTENCES, verify=BOTH_SUPPORTED)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)  # longer than the keep-alive interval below
        return answer(request)

    monkeypatch.setattr(chat_router, "KEEP_ALIVE_S", 0.05)
    client, token, wid = _ready(tmp_path, monkeypatch, slow)
    r = client.post(
        f"/api/v1/workspaces/{wid}/chat", json={"message": QUESTION}, headers={**_h(token), "Accept": "text/event-stream"}
    )
    assert ": keep-alive\n\n" in r.text
    blocks = [b for b in r.text.strip().split("\n\n") if not b.startswith(":")]
    assert _events("\n\n".join(blocks))[-1][0] == "done"
