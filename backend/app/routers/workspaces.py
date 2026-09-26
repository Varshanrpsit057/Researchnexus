"""Research-workspace endpoints (Roadmap Phase 8; API spec §5).

Delivered: workspace CRUD, the paper collection (add / remove / pin / tag /
annotate / reorder), and the trail-review surface (grouped read + accept /
reject). Every route is tenant-scoped through `deps.CurrentUser`; a
workspace owned by someone else is a `404`, never a `403` (API spec
§Tenant isolation).

`GET .../graph` (Phase 13) returns the workspace's `ResearchGraph`,
rebuilt fresh from the current paper collection and trail on every call
(app/services/workspace/pipeline.py::get_graph).

`GET .../activity` (Phase 14) reads the workspace's `stage_runs` --
the orchestrator's append-only tool-call log. Hashes and counts only,
never a prompt or response body (Data Model §13).

Deferred to later phases (kept out per the Phase 8 brief):
- the async `202 -> Job(kind=index_rebuild|workspace_delete|trail)` variants
  -- the index rebuild runs inline in the service layer and delete is
  synchronous here;
- `POST .../papers` with a `{ "manual": {doi|arxiv_id|url} }` body -- manual
  metadata resolution reuses the Phase 4 external clients and is wired when
  that flow is built;
- `POST .../trail/retype` -- trail regeneration is Phase 7 pipeline work.
- synthesis routes (chat / summary / keypoints / compare / gaps /
  directions / citations / presentation) -- Phases 9-14.
- GraphRAG routing over the research graph -- Phase 14+.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db
from app.deps import CurrentUser
from app.domain.orchestrator import StageName
from app.domain.trail import UserState
from app.services.workspace import pipeline

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


# --- request bodies ---------------------------------------------------------


class CreateWorkspaceBody(BaseModel):
    title: str
    seed_paper_id: str
    import_run_id: str | None = None
    # the workspace's estimated-spend cap: a zero or negative one would block every model stage
    token_budget_usd: float = Field(default=5.0, gt=0)


class UpdateWorkspaceBody(BaseModel):
    title: str | None = None
    token_budget_usd: float | None = Field(default=None, gt=0)


class AddPapersBody(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    from_run_id: str | None = None


class UpdatePaperBody(BaseModel):
    pinned: bool | None = None
    tags: list[str] | None = None
    note: str | None = None
    order: int | None = None


class EdgeStateBody(BaseModel):
    user_state: str


# --- serialisers ----------------------------------------------------------


def _workspace_json(ws: object, *, counts: dict | None = None) -> dict:
    payload = ws.model_dump(mode="json")  # type: ignore[attr-defined]
    payload["cost_used"] = payload.get("cost_used_usd")
    if counts is not None:
        payload["counts"] = counts
    return payload


# --- workspace CRUD -----------------------------------------------------


@router.post("", status_code=201)
def create_workspace(
    body: CreateWorkspaceBody, db: DbSession, settings: AppSettings, current_user: CurrentUser
) -> dict:
    try:
        ws = pipeline.create_workspace(
            db,
            owner=current_user,
            req=pipeline.WorkspaceCreateRequest(
                title=body.title,
                seed_paper_id=body.seed_paper_id,
                import_run_id=body.import_run_id,
                token_budget_usd=body.token_budget_usd,
            ),
            settings=settings,
        )
    except pipeline.PaperNotFound as e:
        raise _err(404, "not_found", "seed paper not found") from e
    except pipeline.SeedNotAnalyzed as e:
        raise _err(409, "conflict", "seed paper must be analysed first (full text + profile)") from e
    return _workspace_json(ws)


@router.get("")
def list_workspaces(db: DbSession, current_user: CurrentUser) -> dict:
    items = pipeline.list_workspaces(db, owner=current_user)
    return {"workspaces": [_workspace_json(w) for w in items], "next_cursor": None}


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    try:
        ws = pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    return _workspace_json(ws, counts=repo.workspace_child_counts(db, workspace_id))


@router.patch("/{workspace_id}")
def update_workspace(
    workspace_id: str, body: UpdateWorkspaceBody, db: DbSession, current_user: CurrentUser
) -> dict:
    try:
        ws = pipeline.update_workspace(
            db,
            owner=current_user,
            workspace_id=workspace_id,
            title=body.title,
            token_budget_usd=body.token_budget_usd,
        )
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    return _workspace_json(ws)


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: str, db: DbSession, current_user: CurrentUser
) -> Response:
    try:
        pipeline.delete_workspace(db, owner=current_user, workspace_id=workspace_id)
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    return Response(status_code=204)


# --- paper collection --------------------------------------------------


@router.post("/{workspace_id}/papers", status_code=201)
def add_papers(
    workspace_id: str,
    body: AddPapersBody,
    db: DbSession,
    settings: AppSettings,
    current_user: CurrentUser,
) -> dict:
    try:
        ws, added = pipeline.add_papers(
            db,
            owner=current_user,
            workspace_id=workspace_id,
            paper_ids=body.paper_ids,
            from_run_id=body.from_run_id,
            settings=settings,
        )
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    except pipeline.PaperNotFound as e:
        raise _err(404, "not_found", f"paper not found: {e}") from e
    return {"workspace": _workspace_json(ws), "added": added}


@router.delete("/{workspace_id}/papers/{paper_id}")
def remove_paper(
    workspace_id: str,
    paper_id: str,
    db: DbSession,
    settings: AppSettings,
    current_user: CurrentUser,
) -> dict:
    try:
        ws = pipeline.remove_paper(
            db, owner=current_user, workspace_id=workspace_id, paper_id=paper_id, settings=settings
        )
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    except pipeline.CannotRemoveSeed as e:
        raise _err(409, "conflict", "the seed paper cannot be removed") from e
    except pipeline.PaperNotFound as e:
        raise _err(404, "not_found", "paper is not in this workspace") from e
    return _workspace_json(ws)


@router.patch("/{workspace_id}/papers/{paper_id}")
def update_paper(
    workspace_id: str,
    paper_id: str,
    body: UpdatePaperBody,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    try:
        wp = pipeline.update_paper(
            db, owner=current_user, workspace_id=workspace_id, paper_id=paper_id, changes=changes
        )
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    except pipeline.PaperNotFound as e:
        raise _err(404, "not_found", "paper is not in this workspace") from e
    return wp.model_dump(mode="json")


# --- trail review (Stage S12) --------------------------------------


@router.get("/{workspace_id}/trail")
def get_trail(
    workspace_id: str,
    db: DbSession,
    current_user: CurrentUser,
    type: Annotated[str | None, Query()] = None,
    band: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
) -> dict:
    # "all" returns every edge, rejected ones included, in one read (each
    # carries its own user_state); omitted = pending + accepted
    if state is not None and state not in {s.value for s in UserState} | {"all"}:
        raise _err(422, "invalid_parameter", "state must be pending|accepted|rejected|all")
    try:
        return pipeline.grouped_trail(
            db,
            owner=current_user,
            workspace_id=workspace_id,
            type_filter=type,
            band=band,
            state=state,
        )
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e


@router.post("/{workspace_id}/trail/{edge_id}")
def set_edge_state(
    workspace_id: str,
    edge_id: str,
    body: EdgeStateBody,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    try:
        state = UserState(body.user_state)
    except ValueError as e:
        raise _err(422, "invalid_parameter", "user_state must be accepted|rejected|pending") from e
    try:
        return pipeline.set_edge_state(
            db, owner=current_user, workspace_id=workspace_id, edge_id=edge_id, state=state
        )
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    except pipeline.PaperNotFound as e:
        raise _err(404, "not_found", "trail edge not found in this workspace") from e


# --- research graph (Roadmap Phase 13) ----------------------------------


@router.get("/{workspace_id}/graph")
def get_graph(workspace_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    try:
        graph = pipeline.get_graph(db, owner=current_user, workspace_id=workspace_id)
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    return graph.model_dump(mode="json")


# --- activity / tool-call log (Roadmap Phase 14) ------------------------


@router.get("/{workspace_id}/activity")
def get_activity(
    workspace_id: str,
    db: DbSession,
    current_user: CurrentUser,
    stage: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    stage_filter: StageName | None = None
    if stage is not None:
        try:
            stage_filter = StageName(stage)
        except ValueError as e:
            raise _err(422, "invalid_parameter", "stage must be one of " + ", ".join(s.value for s in StageName)) from e
    try:
        rows = pipeline.get_activity(db, owner=current_user, workspace_id=workspace_id, stage=stage_filter, limit=limit)
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    return {"stage_runs": [r.model_dump(mode="json") for r in rows]}
