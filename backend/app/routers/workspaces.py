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

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db, get_session_factory
from app.deps import CurrentUser
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.orchestrator import StageName
from app.domain.trail import UserState
from app.domain.workspace import ResearchWorkspace
from app.jobs.runner import new_id, run_fulltext_job
from app.services.fulltext.batch import papers_to_read
from app.services.fulltext.retrieve import coverage_of
from app.services.trail.workspace_trail import NothingToConnect, build_workspace_trail
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


class UpdateWorkspaceBody(BaseModel):
    title: str | None = None


class AddPapersBody(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    from_run_id: str | None = None


class UpdatePaperBody(BaseModel):
    pinned: bool | None = None
    # bounded, so a note or tag list can't grow without limit (2026-10-06)
    tags: list[Annotated[str, Field(max_length=60)]] | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=4000)
    order: int | None = None


class EdgeStateBody(BaseModel):
    user_state: str


# --- serialisers ----------------------------------------------------------


def _workspace_json(ws: object, *, counts: dict | None = None) -> dict:
    payload = ws.model_dump(mode="json")  # type: ignore[attr-defined]
    if counts is not None:
        payload["counts"] = counts
    return payload


# --- full text (remediation Phase 7) ------------------------------------------------

COVERAGE_STATES = ("full_text", "abstract_only", "retrieval_failed", "no_text")
# a job still "running" this long after its last progress died with its server
_STALE_JOB = timedelta(minutes=15)


def _in_progress(job: Job) -> bool:
    return job.status in (JobStatus.QUEUED, JobStatus.RUNNING) and datetime.now(timezone.utc) - job.updated_at < _STALE_JOB


def _job_json(job: Job) -> dict:
    # a run whose server stopped under it is over, not "running" forever
    interrupted = job.status in (JobStatus.QUEUED, JobStatus.RUNNING) and not _in_progress(job)
    return {
        "job_id": job.job_id,
        "kind": job.kind.value,
        "status": JobStatus.FAILED.value if interrupted else job.status.value,
        "progress": job.progress,
        "error": "The run was interrupted before it finished." if interrupted else job.error,
        "poll_url": f"/api/v1/jobs/{job.job_id}",
    }


def _start_fulltext(
    db: Session, background_tasks: BackgroundTasks, workspace: ResearchWorkspace, owner_id: str, settings: Settings, *, force: bool
) -> Job | None:
    """Looks for the full text of the workspace's abstract-only papers in the
    background; the one already running if there is one; None when every
    paper that could have it already does."""
    current = repo.latest_job(db, workspace.workspace_id, JobKind.FULLTEXT)
    if current is not None and _in_progress(current):
        return current
    if not papers_to_read(db, workspace):
        return None
    job = repo.create_job(db, Job(job_id=new_id("job"), owner_id=owner_id, workspace_id=workspace.workspace_id, kind=JobKind.FULLTEXT))
    background_tasks.add_task(run_fulltext_job, get_session_factory(), job.job_id, workspace.workspace_id, owner_id, settings, force)
    return job


# --- workspace CRUD -----------------------------------------------------


@router.post("", status_code=201)
def create_workspace(
    body: CreateWorkspaceBody,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
    current_user: CurrentUser,
) -> dict:
    try:
        ws = pipeline.create_workspace(
            db,
            owner=current_user,
            req=pipeline.WorkspaceCreateRequest(
                title=body.title,
                seed_paper_id=body.seed_paper_id,
                import_run_id=body.import_run_id,
            ),
            settings=settings,
        )
    except pipeline.PaperNotFound as e:
        raise _err(404, "not_found", "seed paper not found") from e
    except pipeline.SeedNotAnalyzed as e:
        raise _err(409, "conflict", "seed paper must be analysed first (full text + profile)") from e
    if settings.fulltext_auto:
        _start_fulltext(db, background_tasks, ws, current_user.id, settings, force=False)
    return _workspace_json(ws)


@router.get("")
def list_workspaces(db: DbSession, current_user: CurrentUser) -> dict:
    items = pipeline.list_workspaces(db, owner=current_user)
    # each with its seed's title and what it holds, so the list says which is which
    counts = repo.workspaces_child_counts(db, [w.workspace_id for w in items])
    titles = repo.paper_titles(db, {w.seed_paper_id for w in items})
    return {
        "workspaces": [
            {**_listed(_workspace_json(w, counts=counts[w.workspace_id])), "seed_title": titles.get(w.seed_paper_id)} for w in items
        ],
        "next_cursor": None,
    }


def _listed(payload: dict) -> dict:
    """A workspace as the list shows it: its papers without their ranking
    snapshots (the overview reads those from the workspace itself), which
    made the list megabytes long for a reader with many workspaces."""
    return {**payload, "papers": [{**p, "ranking_snapshot": None} for p in payload["papers"]]}


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
    background_tasks: BackgroundTasks,
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
    job = _start_fulltext(db, background_tasks, ws, current_user.id, settings, force=False) if settings.fulltext_auto else None
    return {"workspace": _workspace_json(ws), "added": added, "fulltext_job": _job_json(job) if job else None}


@router.get("/{workspace_id}/coverage")
def get_coverage(workspace_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    """What text each paper is read from -- full text, abstract only,
    retrieval failed, no text -- and the latest full-text run."""
    try:
        ws = pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    papers = []
    summary: Counter[str] = Counter()
    for wp in ws.papers:
        paper = repo.get_paper(db, wp.paper_id)
        if paper is None:
            continue
        coverage = coverage_of(paper)
        summary[str(coverage["state"])] += 1
        papers.append({"paper_id": wp.paper_id, "title": paper.title, "role": wp.role.value, "coverage": coverage})
    job = repo.latest_job(db, workspace_id, JobKind.FULLTEXT)
    return {"papers": papers, "summary": {s: summary.get(s, 0) for s in COVERAGE_STATES}, "job": _job_json(job) if job else None}


@router.post("/{workspace_id}/fulltext", status_code=202)
def retrieve_workspace_full_text(
    workspace_id: str, background_tasks: BackgroundTasks, db: DbSession, settings: AppSettings, current_user: CurrentUser
) -> dict:
    """Looks again for the full text of every paper that only has its abstract."""
    try:
        ws = pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    job = _start_fulltext(db, background_tasks, ws, current_user.id, settings, force=True)
    return {"job": _job_json(job) if job else None}


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


@router.post("/{workspace_id}/trail/build")
async def build_trail_from_papers(
    workspace_id: str, db: DbSession, settings: AppSettings, current_user: CurrentUser
) -> dict:
    """Connect the workspace's own papers to its seed (remediation,
    2026-10-02): the trail a discovery run gives, for papers the reader
    uploaded or added. Rebuilt in place; decisions already made are kept."""
    try:
        workspace = pipeline.get_workspace(db, owner=current_user, workspace_id=workspace_id)
    except pipeline.WorkspaceNotFound as e:
        raise _err(404, "not_found", "workspace not found") from e
    if repo.get_profile(db, workspace.seed_paper_id) is None:
        raise _err(409, "seed_not_analyzed", "analyse the seed paper first: the trail compares each paper with its profile")
    try:
        result = await build_workspace_trail(db, workspace=workspace, owner_id=current_user.id, settings=settings)
    except NothingToConnect as e:
        raise _err(409, "nothing_to_connect", "this workspace holds only its seed paper; add papers to connect") from e
    return {
        "run_id": result.run_id,
        "papers": result.papers,
        "edges": result.edges,
        "connected_papers": result.connected_papers,
        "unconnected_papers": result.unconnected_papers,
    }


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
