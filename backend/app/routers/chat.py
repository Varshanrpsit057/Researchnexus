"""Multi-paper RAG chat (API spec §6 `POST /workspaces/{id}/chat`,
`GET /workspaces/{id}/chat/sessions[/{sid}]`; Roadmap Phase 9).

Streaming and non-streaming share one code path: the RAG pipeline produces
a complete, verified `RagAnswer` (citations are known before the first
token is rendered), then the SSE branch replays it as
`token` / `citation` / `usage` / `done` events. A non-answerable turn emits
a single `done` with `answerable:false` and bills no generation tokens.

`mode:"themes"` currently falls back to normal QA with a warning -- the
per-workspace GraphRAG route is Phase 13.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db
from app.deps import CurrentUser
from app.domain.chat import ChatMessage, ChatRole, ChatSession
from app.domain.rag import RagAnswer
from app.jobs.runner import new_id
from app.llm.session import resolve_llm_session
from app.services.rag.pipeline import RagRequest, answer_question, build_answer_claims
from app.services.workspace import pipeline as ws_pipeline

router = APIRouter(prefix="/api/v1/workspaces", tags=["chat"])

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


class ChatBody(BaseModel):
    message: str
    session_id: str | None = None
    scope: dict | str = "all"
    mode: str = "qa"


def _scope_ids(scope: dict | str) -> list[str] | None:
    if isinstance(scope, dict) and scope.get("paper_ids"):
        return [str(p) for p in scope["paper_ids"]]
    return None


def _claims_payload(db: Session, claims: list) -> list[dict]:
    return [c.model_dump(mode="json") for c in claims]


@router.post("/{workspace_id}/chat")
async def chat(
    workspace_id: str,
    body: ChatBody,
    db: DbSession,
    settings: AppSettings,
    current_user: CurrentUser,
    accept: Annotated[str | None, Header()] = None,
) -> object:
    try:
        workspace = ws_pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except ws_pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e

    session = resolve_llm_session(db, current_user, settings)
    if session is None:
        raise _err(409, "llm_key_required", "no working LLM provider key saved")

    if body.session_id is not None:
        if repo.get_chat_session(db, body.session_id, workspace_id=workspace_id, owner_id=current_user.id) is None:
            raise _err(404, "not_found", "chat session not found")
        chat_session_id = body.session_id
    else:
        chat_session_id = new_id("cs")
        repo.create_chat_session(
            db,
            ChatSession(
                session_id=chat_session_id,
                workspace_id=workspace_id,
                owner_id=current_user.id,
                title=body.message[:80],
            ),
        )

    repo.add_chat_message(
        db,
        ChatMessage(message_id=new_id("cm"), session_id=chat_session_id, role=ChatRole.USER, content=body.message),
    )

    warnings: list[str] = []
    if body.mode == "themes":
        warnings.append("graphrag_not_available")

    answer = await answer_question(
        db,
        workspace=workspace,
        request=RagRequest(query=body.message, scope_paper_ids=_scope_ids(body.scope)),
        session=session,
        settings=settings,
    )
    answer.warnings.extend(warnings)

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
            session_id=chat_session_id,
            role=ChatRole.ASSISTANT,
            content=answer.text,
            citations=[c.claim_id for c in claims],
            tokens_prompt=answer.prompt_tokens,
            tokens_completion=answer.completion_tokens,
            faithfulness=answer.faithfulness,
            answerable=answer.answerable,
        ),
    )

    if accept and "text/event-stream" in accept:
        return StreamingResponse(
            _sse(answer, message_id=message_id, session_id=chat_session_id, claims=claims, db=db),
            media_type="text/event-stream",
        )
    return {
        "message_id": message_id,
        "session_id": chat_session_id,
        "text": answer.text,
        "answerable": answer.answerable,
        "faithfulness": answer.faithfulness,
        "unsupported_dropped": answer.unsupported_dropped,
        "suggestion": answer.suggestion,
        "claims": _claims_payload(db, claims),
        "warnings": answer.warnings,
    }


def _sse(answer: RagAnswer, *, message_id: str, session_id: str, claims: list, db: Session):
    def event(name: str, data: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(data)}\n\n"

    if not answer.answerable:
        yield event(
            "done",
            {
                "message_id": message_id,
                "session_id": session_id,
                "answerable": False,
                "suggestion": answer.suggestion,
            },
        )
        return

    for word in answer.text.split(" "):
        if word:
            yield event("token", {"text": word + " "})

    chunk_meta = {c.chunk_id: c for c in repo.get_chunks_by_ids(db, answer.used_chunk_ids)}
    for i, claim in enumerate(claims, start=1):
        cid = claim.supporting_chunk_ids[0]
        meta = chunk_meta.get(cid)
        yield event(
            "citation",
            {
                "marker": f"[{i}]",
                "claim_id": claim.claim_id,
                "paper_id": claim.supporting_paper_ids[0] if claim.supporting_paper_ids else None,
                "chunk_id": cid,
                "quote": (meta.text[:280] if meta else ""),
                "section": meta.section if meta else None,
                "page": meta.page if meta else None,
            },
        )

    yield event("usage", {"prompt": answer.prompt_tokens, "completion": answer.completion_tokens})
    yield event(
        "done",
        {
            "message_id": message_id,
            "session_id": session_id,
            "faithfulness": answer.faithfulness,
            "answerable": True,
            "unsupported_dropped": answer.unsupported_dropped,
        },
    )


@router.get("/{workspace_id}/chat/sessions")
def list_sessions(workspace_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    try:
        ws_pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except ws_pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    sessions = repo.list_chat_sessions(db, workspace_id, current_user.id)
    return {"sessions": [s.model_dump(mode="json") for s in sessions]}


@router.get("/{workspace_id}/chat/sessions/{session_id}")
def get_session(workspace_id: str, session_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    try:
        ws_pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except ws_pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    session = repo.get_chat_session(db, session_id, workspace_id=workspace_id, owner_id=current_user.id)
    if session is None:
        raise _err(404, "not_found", "chat session not found")

    messages = repo.get_chat_messages(db, session_id)
    out: list[dict] = []
    for m in messages:
        payload = m.model_dump(mode="json")
        if m.role is ChatRole.ASSISTANT and m.citations:
            payload["claims"] = [
                c.model_dump(mode="json")
                for c in repo.get_claims_for_artefact(db, m.message_id)
            ]
        out.append(payload)
    return {"session": session.model_dump(mode="json"), "messages": out}
