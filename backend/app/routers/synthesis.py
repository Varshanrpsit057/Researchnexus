"""Workspace synthesis (API spec §6 `POST /workspaces/{id}/summary`,
`/keypoints`, `/citations`; Roadmap Phase 9).

`summary` / `keypoints` need a working LLM key (`409 llm_key_required`);
`citations` is fully deterministic and needs none. Every returned claim /
key point resolves to a real `paper_chunks` span, and every reference
string is built by the deterministic formatter -- never generated.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db
from app.deps import CurrentUser
from app.domain.rag import FilteredChunk
from app.jobs.runner import new_id
from app.llm.session import resolve_llm_session
from app.services.citations.metadata_resolver import to_citation
from app.services.synthesis.keypoints import extract_keypoints
from app.services.synthesis.summary import summarize
from app.services.workspace import pipeline as ws_pipeline

router = APIRouter(prefix="/api/v1/workspaces", tags=["synthesis"])

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

_MAX_CHUNKS_PER_PAPER = 6


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


def _require_ws(db: Session, current_user: object, workspace_id: str):  # noqa: ANN001,ANN202
    try:
        return ws_pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)  # type: ignore[arg-type]
    except ws_pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e


def _scope_papers(workspace, scope: dict | str) -> list[str]:  # noqa: ANN001
    member_ids = [p.paper_id for p in workspace.papers]
    if isinstance(scope, dict) and scope.get("paper_ids"):
        wanted = {str(p) for p in scope["paper_ids"]}
        return [pid for pid in member_ids if pid in wanted]
    return member_ids


class SummaryBody(BaseModel):
    scope: dict | str = "all"
    length: str = "medium"


@router.post("/{workspace_id}/summary")
async def summary(
    workspace_id: str, body: SummaryBody, db: DbSession, settings: AppSettings, current_user: CurrentUser
) -> dict:
    workspace = _require_ws(db, current_user, workspace_id)
    session = resolve_llm_session(db, current_user, settings)
    if session is None:
        raise _err(409, "llm_key_required", "no working LLM provider key saved")

    chunks: list[FilteredChunk] = []
    for pid in _scope_papers(workspace, body.scope):
        for c in repo.get_chunks_for_paper(db, pid)[:_MAX_CHUNKS_PER_PAPER]:
            chunks.append(
                FilteredChunk(chunk_id=c.chunk_id, paper_id=c.paper_id, text=c.text, section=c.section, page=c.page, kept=True)
            )

    result = await summarize(session, chunks, length=body.length, faithfulness_min=settings.rag_faithfulness_min)
    summary_id = new_id("sum")
    claims = result.to_claims(workspace_id=workspace_id, artefact_id=summary_id)
    chunk_to_paper = {c.chunk_id: c.paper_id for c in chunks}
    claims = [
        c.model_copy(update={"supporting_paper_ids": sorted({chunk_to_paper[x] for x in c.supporting_chunk_ids if x in chunk_to_paper})})
        for c in claims
    ]
    repo.save_claims(db, claims)
    return {
        "summary_id": summary_id,
        "text": result.text,
        "faithfulness": result.faithfulness,
        "unsupported_dropped": result.unsupported_dropped,
        "claims": [c.model_dump(mode="json") for c in claims],
        "warnings": result.warnings,
    }


class KeypointsBody(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)


@router.post("/{workspace_id}/keypoints")
async def keypoints(
    workspace_id: str, body: KeypointsBody, db: DbSession, settings: AppSettings, current_user: CurrentUser
) -> dict:
    workspace = _require_ws(db, current_user, workspace_id)
    session = resolve_llm_session(db, current_user, settings)
    if session is None:
        raise _err(409, "llm_key_required", "no working LLM provider key saved")

    member_ids = {p.paper_id for p in workspace.papers}
    targets = [pid for pid in body.paper_ids if pid in member_ids] or list(member_ids)

    papers_out: list[dict] = []
    for pid in targets:
        result = await extract_keypoints(session, pid, repo.get_chunks_for_paper(db, pid))
        papers_out.append(
            {
                "paper_id": pid,
                "points": [
                    {"facet": p.facet, "text": p.text, "span": p.span.model_dump(mode="json")} for p in result.points
                ],
                "warnings": result.warnings,
            }
        )
    return {"papers": papers_out}


class CitationsBody(BaseModel):
    paper_ids: list[str] | str = "all"
    formats: list[str] = Field(default_factory=lambda: ["apa", "ieee", "bibtex"])


@router.post("/{workspace_id}/citations")
def citations(
    workspace_id: str, body: CitationsBody, db: DbSession, current_user: CurrentUser
) -> dict:
    workspace = _require_ws(db, current_user, workspace_id)
    member_ids = [p.paper_id for p in workspace.papers]
    if isinstance(body.paper_ids, list) and body.paper_ids:
        wanted = set(body.paper_ids)
        targets = [pid for pid in member_ids if pid in wanted]
    else:
        targets = member_ids

    formats = [f for f in body.formats if f in {"apa", "ieee", "bibtex"}] or ["apa", "ieee", "bibtex"]
    built: list[dict] = []
    unresolved: list[str] = []
    for i, pid in enumerate(targets, start=1):
        paper = repo.get_paper(db, pid)
        if paper is None:
            unresolved.append(pid)
            continue
        citation = to_citation(workspace_id, paper, number=i)
        repo.upsert_citation(db, citation, owner_id=current_user.id)
        entry = {
            "paper_id": pid,
            "resolved_from": citation.resolved_from,
            "formatted": {f: citation.formatted.get(f, "Not available") for f in formats},
        }
        built.append(entry)
        if citation.resolved_from == "unresolved":
            unresolved.append(pid)
    return {"citations": built, "unresolved": unresolved}
