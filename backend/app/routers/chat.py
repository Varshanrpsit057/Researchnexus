"""Multi-paper RAG chat (API spec §6 `POST /workspaces/{id}/chat`,
`GET /workspaces/{id}/chat/sessions[/{sid}]`; Roadmap Phase 9).

Streaming and non-streaming share one pipeline run. The RAG pipeline
produces a complete, verified `RagAnswer` -- every sentence is checked
against its source before any of it is shown -- so the SSE branch streams
in two parts:

- while the pipeline works: `status` events naming each stage as it starts
  (searching, reading, writing, checking, rewriting);
- then the verified answer, sentence by sentence: `token` events for a
  sentence's words, immediately followed by that sentence's `citation`
  (so a citation arrives exactly where it belongs in the text), then
  `usage` and `done`. A failure mid-way is an `error` event.

While a stage runs, a `: keep-alive` comment every 15 s keeps the
connection from being dropped as idle.

Failures say what actually happened: a provider failure is `provider_error`
with its `kind` (auth, insufficient_balance, rate_limited, timeout,
unavailable, bad_request, bad_response) and a message naming the provider;
an answer the model couldn't write is `generation_failed`; one that
couldn't be checked against its sources is `verification_failed`; one with
no sentence its sources support is `unsupported_answer`. None of them is
saved. Every provider call a turn makes -- a failed turn's too -- is
recorded with its token usage (app/llm/usage.py).

A turn is persisted only once it has an answer: the question, the answer,
its claims, and the answer's outcome (suggestion when not answerable,
sentences dropped for lacking support, warnings) are written together, so a
failed attempt leaves nothing behind and retrying it cannot duplicate the
question. `regenerate: true` re-answers a conversation's last question,
replacing its answer.

Session detail resolves every claim's supporting chunks into sources
(paper, section, page, quote) from the stored chunks, so a reloaded
conversation shows the same evidence as a live one.

`mode:"themes"` currently falls back to normal QA with a warning -- the
per-workspace GraphRAG route is Phase 13.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db, get_session_factory
from app.deps import CurrentUser
from app.domain.chat import ChatMessage, ChatRole, ChatSession
from app.domain.citation import Claim
from app.domain.rag import RagAnswer
from app.domain.user import User
from app.domain.workspace import ResearchWorkspace
from app.jobs.runner import new_id
from app.llm.client import LlmProviderError, describe_provider_error
from app.llm.session import LlmSession, resolve_llm_session
from app.llm.usage import usage_scope
from app.services.rag.pipeline import (
    RagRequest,
    RagStage,
    StageHook,
    answer_question,
    build_answer_claims,
)
from app.services.workspace import pipeline as ws_pipeline
from app.telemetry.logging import get_logger

router = APIRouter(prefix="/api/v1/workspaces", tags=["chat"])
_log = get_logger(__name__)

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

QUOTE_MAX = 700
KEEP_ALIVE_S = 15.0
GENERATION_ERROR = "The language model didn't return a usable answer. Try again in a moment."
VERIFICATION_ERROR = "The answer couldn't be checked against its sources, so it isn't shown. Try again."
UNSUPPORTED_ERROR = (
    "No sentence of the answer could be matched to a passage in this workspace, so none is shown. "
    "Try asking again, or rephrase the question."
)
INTERNAL_ERROR = "Something went wrong while answering. Try again."


class _GenerationFailed(Exception):
    """The turn produced no answer to show: the model's reply couldn't be
    used, couldn't be checked, or no sentence of it was supported. A chat
    turn with no answer is a failed turn, not an empty one: nothing is
    persisted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _provider_error(e: LlmProviderError) -> dict[str, str]:
    return {"code": "provider_error", "kind": e.kind.value, "message": describe_provider_error(e)}


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


class ChatBody(BaseModel):
    message: str = ""
    session_id: str | None = None
    scope: dict | str = "all"
    mode: str = "qa"
    # re-answer the conversation's last question, replacing its answer
    regenerate: bool = False


def _scope_ids(scope: dict | str) -> list[str] | None:
    if isinstance(scope, dict) and scope.get("paper_ids"):
        return [str(p) for p in scope["paper_ids"]]
    return None


@dataclass
class _Turn:
    """A validated chat request, ready to answer."""

    workspace: ResearchWorkspace
    llm: LlmSession
    owner: User
    question: str
    session_id: str | None  # None: a new conversation, created once answered
    regenerate: bool
    replace_ids: list[str] = field(default_factory=list)  # answers a regeneration replaces
    scope_ids: list[str] | None = None
    warnings: list[str] = field(default_factory=list)


def _prepare(db: Session, workspace_id: str, body: ChatBody, owner: User, settings: Settings) -> _Turn:
    try:
        workspace = ws_pipeline.get_workspace(db, owner=owner, workspace_id=workspace_id)
    except ws_pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e

    llm = resolve_llm_session(db, owner, settings)
    if llm is None:
        raise _err(409, "llm_key_required", "no working LLM provider key saved")

    if body.session_id is not None and (
        repo.get_chat_session(db, body.session_id, workspace_id=workspace_id, owner_id=owner.id) is None
    ):
        raise _err(404, "not_found", "chat session not found")

    warnings = ["graphrag_not_available"] if body.mode == "themes" else []
    turn = _Turn(
        workspace=workspace,
        llm=llm,
        owner=owner,
        question=body.message.strip(),
        session_id=body.session_id,
        regenerate=body.regenerate,
        scope_ids=_scope_ids(body.scope),
        warnings=warnings,
    )
    if body.regenerate:
        if body.session_id is None:
            raise _err(422, "session_required", "regenerate needs the conversation's session_id")
        history = repo.get_chat_messages(db, body.session_id)
        last_q = max((i for i, m in enumerate(history) if m.role is ChatRole.USER), default=None)
        if last_q is None:
            raise _err(409, "nothing_to_regenerate", "this conversation has no question to answer again")
        turn.question = history[last_q].content
        turn.replace_ids = [m.message_id for m in history[last_q + 1 :] if m.role is ChatRole.ASSISTANT]
    elif not turn.question:
        raise _err(422, "empty_message", "ask a question first")
    return turn


async def _answer(db: Session, turn: _Turn, settings: Settings, on_stage: StageHook | None = None) -> RagAnswer:
    with usage_scope("chat", workspace_id=turn.workspace.workspace_id):
        answer = await answer_question(
            db,
            workspace=turn.workspace,
            request=RagRequest(query=turn.question, scope_paper_ids=turn.scope_ids),
            session=turn.llm,
            settings=settings,
            on_stage=on_stage,
        )
    if answer.answerable and not answer.sentences:
        if "generation_failed" in answer.warnings:
            raise _GenerationFailed("generation_failed", GENERATION_ERROR)
        if "verification_failed" in answer.warnings:
            raise _GenerationFailed("verification_failed", VERIFICATION_ERROR)
        raise _GenerationFailed("unsupported_answer", UNSUPPORTED_ERROR)
    answer.warnings.extend(turn.warnings)
    return answer


def _persist(db: Session, turn: _Turn, answer: RagAnswer) -> tuple[str, str, list[Claim]]:
    """Write the answered turn: its conversation (if new), the question
    (unless regenerating), and the answer with its claims and outcome."""
    workspace_id = turn.workspace.workspace_id
    session_id = turn.session_id
    if session_id is None:
        session_id = new_id("cs")
        repo.create_chat_session(
            db,
            ChatSession(session_id=session_id, workspace_id=workspace_id, owner_id=turn.owner.id, title=turn.question[:80]),
        )
    if not turn.regenerate:
        repo.add_chat_message(
            db, ChatMessage(message_id=new_id("cm"), session_id=session_id, role=ChatRole.USER, content=turn.question)
        )
    for old in turn.replace_ids:
        repo.delete_chat_message(db, old)

    message_id = new_id("cm")
    chunk_to_paper = {c.chunk_id: c.paper_id for c in repo.get_chunks_by_ids(db, answer.used_chunk_ids)}
    claims = build_answer_claims(
        answer,
        workspace_id=workspace_id,
        message_id=message_id,
        retrieved_chunk_ids=set(answer.used_chunk_ids),
        chunk_to_paper=chunk_to_paper,
    )
    repo.save_claims(db, claims)
    repo.add_chat_message(
        db,
        ChatMessage(
            message_id=message_id,
            session_id=session_id,
            role=ChatRole.ASSISTANT,
            content=answer.text,
            citations=[c.claim_id for c in claims],
            tokens_prompt=answer.prompt_tokens,
            tokens_completion=answer.completion_tokens,
            faithfulness=answer.faithfulness,
            answerable=answer.answerable,
            suggestion=answer.suggestion,
            unsupported_dropped=answer.unsupported_dropped,
            warnings=list(answer.warnings),
        ),
    )
    return message_id, session_id, claims


def _sources(db: Session, claims: list[Claim]) -> dict[str, list[dict]]:
    """claim id -> the passages that support it: paper, section, page, quote."""
    chunk_ids = sorted({cid for c in claims for cid in c.supporting_chunk_ids})
    chunks = {c.chunk_id: c for c in repo.get_chunks_by_ids(db, chunk_ids)}
    titles: dict[str, str | None] = {}
    out: dict[str, list[dict]] = {}
    for claim in claims:
        sources = []
        for cid in claim.supporting_chunk_ids:
            chunk = chunks.get(cid)
            if chunk is None:
                continue  # the paper left the workspace index; the claim keeps its id only
            if chunk.paper_id not in titles:
                paper = repo.get_paper(db, chunk.paper_id)
                titles[chunk.paper_id] = paper.title if paper is not None else None
            text = chunk.text.strip()
            sources.append(
                {
                    "chunk_id": cid,
                    "paper_id": chunk.paper_id,
                    "paper_title": titles[chunk.paper_id],
                    "section": chunk.section,
                    "page": chunk.page,
                    "quote": text[:QUOTE_MAX],
                    "truncated": len(text) > QUOTE_MAX,
                }
            )
        out[claim.claim_id] = sources
    return out


def _claims_payload(claims: list[Claim], sources: dict[str, list[dict]]) -> list[dict]:
    return [{**c.model_dump(mode="json"), "sources": sources.get(c.claim_id, [])} for c in claims]


def _outcome(answer: RagAnswer, message_id: str, session_id: str, turn: _Turn) -> dict:
    return {
        "message_id": message_id,
        "session_id": session_id,
        "answerable": answer.answerable,
        "faithfulness": answer.faithfulness,
        "unsupported_dropped": answer.unsupported_dropped,
        "suggestion": answer.suggestion,
        "warnings": answer.warnings,
        "replaced_message_ids": turn.replace_ids,
    }


@router.post("/{workspace_id}/chat")
async def chat(
    workspace_id: str,
    body: ChatBody,
    db: DbSession,
    settings: AppSettings,
    current_user: CurrentUser,
    accept: Annotated[str | None, Header()] = None,
) -> object:
    turn = _prepare(db, workspace_id, body, current_user, settings)

    if accept and "text/event-stream" in accept:
        db.close()  # validation is done; the stream opens its own session
        return StreamingResponse(_stream(turn, settings), media_type="text/event-stream")

    try:
        answer = await _answer(db, turn, settings)
    except LlmProviderError as e:
        raise HTTPException(status_code=502, detail={"error": _provider_error(e)}) from e
    except _GenerationFailed as e:
        raise _err(502, e.code, e.message) from e
    message_id, session_id, claims = _persist(db, turn, answer)
    return {
        **_outcome(answer, message_id, session_id, turn),
        "text": answer.text,
        "claims": _claims_payload(claims, _sources(db, claims)),
    }


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


async def _stream(turn: _Turn, settings: Settings) -> AsyncIterator[str]:
    # its own session: the stream outlives the request's dependencies
    db = get_session_factory()()
    stages: asyncio.Queue[RagStage] = asyncio.Queue()
    task = asyncio.create_task(_answer(db, turn, settings, on_stage=stages.put_nowait))
    try:
        # 1. progress, as the pipeline reaches each stage
        while not task.done():
            next_stage = asyncio.ensure_future(stages.get())
            done, _ = await asyncio.wait({task, next_stage}, timeout=KEEP_ALIVE_S, return_when=asyncio.FIRST_COMPLETED)
            if next_stage in done:
                yield _event("status", {"stage": next_stage.result()})
                continue
            next_stage.cancel()
            if not done:
                yield ": keep-alive\n\n"
        while not stages.empty():
            yield _event("status", {"stage": stages.get_nowait()})
        try:
            answer = task.result()
        except LlmProviderError as e:
            _log.warning("chat_provider_error", provider=e.provider, kind=e.kind.value, status=e.status)
            yield _event("error", _provider_error(e))
            return
        except _GenerationFailed as e:
            yield _event("error", {"code": e.code, "message": e.message})
            return
        except Exception:  # noqa: BLE001 - reported to the client, logged here
            _log.exception("chat_stream_failed", workspace_id=turn.workspace.workspace_id)
            yield _event("error", {"code": "internal", "message": INTERNAL_ERROR})
            return

        # 2. the verified answer, each citation right after its sentence
        message_id, session_id, claims = _persist(db, turn, answer)
        sources = _sources(db, claims)
        pending = iter(claims)
        marker = 0
        for sentence in answer.sentences if answer.answerable else []:
            for word in sentence.text.split(" "):
                if word:
                    yield _event("token", {"text": word + " "})
            if not sentence.chunk_ids:
                continue  # flagged, not cited: it has no claim
            claim = next(pending, None)
            if claim is None:
                continue
            marker += 1
            cited = sources.get(claim.claim_id, [])
            first = cited[0] if cited else {}
            yield _event(
                "citation",
                {
                    "marker": f"[{marker}]",
                    "claim_id": claim.claim_id,
                    "sentence": claim.sentence,
                    "paper_id": first.get("paper_id"),
                    "chunk_id": claim.supporting_chunk_ids[0],
                    "quote": first.get("quote", ""),
                    "section": first.get("section"),
                    "page": first.get("page"),
                    "sources": cited,
                },
            )
        yield _event("usage", {"prompt": answer.prompt_tokens, "completion": answer.completion_tokens})
        yield _event("done", _outcome(answer, message_id, session_id, turn))
    finally:
        if not task.done():
            task.cancel()  # the reader went away mid-answer: stop, persist nothing
        db.close()


@router.get("/{workspace_id}/chat/sessions")
def list_sessions(workspace_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    try:
        ws_pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except ws_pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    out = []
    for s in repo.list_chat_sessions(db, workspace_id, current_user.id):
        messages = repo.get_chat_messages(db, s.session_id)
        out.append(
            {
                **s.model_dump(mode="json"),
                "questions": sum(1 for m in messages if m.role is ChatRole.USER),
                "last_active_at": (messages[-1].created_at if messages else s.created_at).isoformat(),
            }
        )
    # most recently active first
    out.sort(key=lambda s: s["last_active_at"], reverse=True)
    return {"sessions": out}


@router.get("/{workspace_id}/chat/sessions/{session_id}")
def get_session(workspace_id: str, session_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    try:
        ws_pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except ws_pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    session = repo.get_chat_session(db, session_id, workspace_id=workspace_id, owner_id=current_user.id)
    if session is None:
        raise _err(404, "not_found", "chat session not found")

    out: list[dict] = []
    for m in repo.get_chat_messages(db, session_id):
        payload = m.model_dump(mode="json")
        if m.role is ChatRole.ASSISTANT and m.citations:
            claims = repo.get_claims_for_artefact(db, m.message_id)
            payload["claims"] = _claims_payload(claims, _sources(db, claims))
        out.append(payload)
    return {"session": session.model_dump(mode="json"), "messages": out}
