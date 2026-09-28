"""Workspace synthesis (API spec §6 `POST /workspaces/{id}/summary`,
`/keypoints`, `/citations`, `/compare`, `/gaps`, `/directions`; Roadmap
Phases 9-12).

`summary` / `keypoints` need a working LLM key (`409 llm_key_required`);
`citations` is fully deterministic and needs none. Every returned claim /
key point resolves to a real `paper_chunks` span, and every reference
string is built by the deterministic formatter -- never generated.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db, get_session_factory
from app.deps import CurrentUser
from app.domain.comparison import ComparisonSchema
from app.domain.direction import DirectionUserState
from app.domain.gap import GapType, GapUserState
from app.domain.jobs import Job, JobKind
from app.domain.rag import FilteredChunk
from app.jobs.runner import new_id, run_gaps_job
from app.llm.session import resolve_llm_session
from app.llm.usage import usage_scope
from app.retrieval.workspace_index import FaissWorkspaceIndex
from app.services.citations.ledger import build_ledger
from app.services.citations.metadata_resolver import to_citation
from app.services.ingest.abstract_chunks import ensure_abstract_chunks
from app.services.orchestrator.orchestrator import ResearchOrchestrator
from app.services.synthesis.compare import build_comparison, build_schema
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

    with usage_scope("summary", workspace_id=workspace_id):
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
        with usage_scope("keypoints", workspace_id=workspace_id):
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


@router.get("/{workspace_id}/citations")
def citation_ledger(workspace_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    # Read-only: every workspace paper with its reference, what discovery
    # knows about it, and every place the workspace cites it. The POST above
    # formats and stores references; nothing read them back until this.
    workspace = _require_ws(db, current_user, workspace_id)
    return build_ledger(db, workspace, owner_id=current_user.id)


class CompareBody(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    schema_: list[str] | None = Field(default=None, alias="schema")

    model_config = {"populate_by_name": True}


@router.post("/{workspace_id}/compare")
async def compare(
    workspace_id: str, body: CompareBody, db: DbSession, settings: AppSettings, current_user: CurrentUser
) -> dict:
    workspace = _require_ws(db, current_user, workspace_id)
    session = resolve_llm_session(db, current_user, settings)
    if session is None:
        raise _err(409, "llm_key_required", "no working LLM provider key saved")

    member_order = [p.paper_id for p in workspace.papers]
    wanted = set(body.paper_ids)
    targets = [pid for pid in member_order if pid in wanted] if wanted else list(member_order)
    if len(targets) < 2:
        raise _err(422, "invalid_parameter", "comparison needs at least 2 workspace papers")

    profiles = [pr for pr in (repo.get_profile(db, pid) for pid in targets) if pr is not None]
    column_schema: ComparisonSchema = build_schema(profiles, explicit=body.schema_)

    index = FaissWorkspaceIndex(
        db,
        workspace_id=workspace_id,
        index_dir=settings.data_dir / "workspace_index",
        vector_backend=settings.rag_vector_backend,
    )
    ensure_abstract_chunks(db, [p.paper_id for p in workspace.papers])
    index.rebuild([p.paper_id for p in workspace.papers])

    with usage_scope("comparison", workspace_id=workspace_id):
        result = await build_comparison(
            db,
            workspace=workspace,
            comparison_id=new_id("cmp"),
            paper_ids=targets,
            column_schema=column_schema,
            session=session,
            settings=settings,
            index=index,
        )
    repo.save_claims(db, result.claims)
    stored = repo.save_comparison(db, result.comparison, owner_id=current_user.id)
    repo.set_workspace_comparison_schema(db, workspace_id, current_user.id, column_schema)

    warnings = list(result.warnings)
    if len(targets) > settings.compare_max_sync_papers:
        warnings.append("large_comparison_ran_sync")
    return {**stored.api_dict(), "warnings": warnings}


@router.get("/{workspace_id}/compare/{comparison_id}")
def get_comparison(
    workspace_id: str, comparison_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    _require_ws(db, current_user, workspace_id)
    comparison = repo.get_comparison(db, comparison_id, workspace_id=workspace_id)
    if comparison is None:
        raise _err(404, "not_found", "comparison not found")
    return comparison.api_dict()


@router.get("/{workspace_id}/compare")
def get_latest_comparison(workspace_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    # `compare` (POST) is synchronous and its result was only ever handed
    # back in that one response -- `list_comparisons` has read the
    # persisted rows back out since Phase 10, but nothing called it, so
    # revisiting Compare after running one showed "no comparison yet"
    # again, indistinguishable from having never run it, until this route.
    _require_ws(db, current_user, workspace_id)
    comparisons = repo.list_comparisons(db, workspace_id)
    if not comparisons:
        raise _err(404, "not_found", "no comparison run yet")
    return comparisons[0].api_dict()


class GapsBody(BaseModel):
    gap_types: list[str] | None = None
    min_supporting_papers: int = 2


@router.post("/{workspace_id}/gaps", status_code=202)
def gaps(
    workspace_id: str,
    body: GapsBody,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
    current_user: CurrentUser,
) -> dict:
    _require_ws(db, current_user, workspace_id)
    if resolve_llm_session(db, current_user, settings) is None:
        raise _err(409, "llm_key_required", "no working LLM provider key saved")
    valid = {t.value for t in GapType}
    bad = [t for t in (body.gap_types or []) if t not in valid]
    if bad:
        raise _err(422, "invalid_parameter", f"unknown gap_types: {bad}")

    job_id = new_id("job")
    repo.create_job(db, Job(job_id=job_id, owner_id=current_user.id, workspace_id=workspace_id, kind=JobKind.GAPS))
    background_tasks.add_task(
        run_gaps_job,
        get_session_factory(),
        job_id,
        workspace_id,
        current_user.id,
        body.gap_types,
        max(2, body.min_supporting_papers),
        settings,
    )
    return {"job": {"job_id": job_id, "kind": "gaps", "status": "queued", "poll_url": f"/api/v1/jobs/{job_id}"}}


@router.get("/{workspace_id}/gaps")
def list_gaps(
    workspace_id: str,
    db: DbSession,
    current_user: CurrentUser,
    state: Annotated[str | None, Query()] = None,
) -> dict:
    _require_ws(db, current_user, workspace_id)
    if state is not None and state not in {s.value for s in GapUserState}:
        raise _err(422, "invalid_parameter", "state must be candidate|accepted|rejected")
    return {"gaps": [g.model_dump(mode="json") for g in repo.get_gaps(db, workspace_id, state=state)]}


class GapStateBody(BaseModel):
    user_state: str


@router.post("/{workspace_id}/gaps/{gap_id}")
def set_gap_state(
    workspace_id: str, gap_id: str, body: GapStateBody, db: DbSession, current_user: CurrentUser
) -> dict:
    _require_ws(db, current_user, workspace_id)
    try:
        state = GapUserState(body.user_state)
    except ValueError as e:
        raise _err(422, "invalid_parameter", "user_state must be accepted|rejected|candidate") from e
    updated = repo.set_gap_user_state(
        db, gap_id, workspace_id=workspace_id, owner_id=current_user.id, state=state
    )
    if updated is None:
        raise _err(404, "not_found", "gap not found in this workspace")
    return updated.model_dump(mode="json")


class DirectionsBody(BaseModel):
    gap_ids: list[str] = Field(default_factory=list)


@router.post("/{workspace_id}/directions")
async def directions(
    workspace_id: str, body: DirectionsBody, db: DbSession, settings: AppSettings, current_user: CurrentUser
) -> dict:
    workspace = _require_ws(db, current_user, workspace_id)
    session = resolve_llm_session(db, current_user, settings)
    if session is None:
        raise _err(409, "llm_key_required", "no working LLM provider key saved")
    if not body.gap_ids:
        raise _err(422, "invalid_parameter", "gap_ids must be a non-empty list of accepted gap ids")

    orchestrator = ResearchOrchestrator(db=db, settings=settings)
    result = await orchestrator.run_directions_stage(
        workspace=workspace, gap_ids=body.gap_ids, session=session, owner_id=current_user.id
    )
    return {
        "directions": [d.model_dump(mode="json") for d in repo.get_directions(db, workspace_id)],
        "requested": result.requested,
        "generated": result.direction_count,
        "skipped_not_accepted": result.skipped_not_accepted,
        "skipped_not_found": result.skipped_not_found,
        "dropped_unsupported": result.dropped_unsupported,
    }


@router.get("/{workspace_id}/directions")
def list_directions(
    workspace_id: str,
    db: DbSession,
    current_user: CurrentUser,
    state: Annotated[str | None, Query()] = None,
    gap_id: Annotated[str | None, Query()] = None,
) -> dict:
    _require_ws(db, current_user, workspace_id)
    if state is not None and state not in {s.value for s in DirectionUserState}:
        raise _err(422, "invalid_parameter", "state must be candidate|accepted|rejected")
    return {
        "directions": [
            d.model_dump(mode="json") for d in repo.get_directions(db, workspace_id, state=state, gap_id=gap_id)
        ]
    }


class DirectionStateBody(BaseModel):
    user_state: str


@router.post("/{workspace_id}/directions/{direction_id}")
def set_direction_state(
    workspace_id: str, direction_id: str, body: DirectionStateBody, db: DbSession, current_user: CurrentUser
) -> dict:
    _require_ws(db, current_user, workspace_id)
    try:
        state = DirectionUserState(body.user_state)
    except ValueError as e:
        raise _err(422, "invalid_parameter", "user_state must be accepted|rejected|candidate") from e
    updated = repo.set_direction_user_state(
        db, direction_id, workspace_id=workspace_id, owner_id=current_user.id, state=state
    )
    if updated is None:
        raise _err(404, "not_found", "direction not found in this workspace")
    return updated.model_dump(mode="json")
