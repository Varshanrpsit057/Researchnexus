"""Research-workspace service layer (Roadmap Phase 8; Architecture §3
S12-S13).

Owns the workspace lifecycle -- create from an analysed seed, add/remove
papers, pin/tag/annotate/reorder, and the trail-review surface (accept /
reject, grouped read). Tenant isolation is enforced here: every entry point
takes the acting `User` and a mismatch surfaces as `WorkspaceNotFound`
(the router turns that into a 404, never a 403 -- API spec §Tenant
isolation).

Every membership change (`create` with an import, `add_papers`,
`remove_paper`) re-runs the workspace combined index
(`app/retrieval/workspace_index.py`) and re-points
`workspaces.combined_index_path`. That index is the deterministic Phase 8
stand-in; Phase 9 swaps in the FAISS-backed implementation behind the same
`WorkspaceChunkIndex` protocol.

`get_graph` (Phase 13) rebuilds the workspace's `ResearchGraph` from its
current papers and non-rejected Phase 7 trail edges on every read and
re-persists it (`workspaces.graph_json`) -- the graph has no state of its
own beyond those two already-authoritative sources, so a fresh, deterministic
rebuild is simpler and safer than an incremental diff and is automatically
correct after any add/remove/accept/reject.

Not in scope (later phases): synthesis (summary/keypoints/compare), gaps,
directions, GraphRAG routing over the research graph, and the async
`index_rebuild` / `trail` jobs -- the rebuild runs inline here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.graph import ResearchGraph
from app.domain.orchestrator import StageName, StageRun
from app.domain.ranking import RankedPaper
from app.domain.trail import RelationshipType, UserState
from app.domain.user import User
from app.domain.workspace import (
    AddedBy,
    Grounding,
    ResearchWorkspace,
    WorkspacePaper,
    WorkspacePaperRole,
    _clean_tags,
)
from app.jobs.runner import new_id
from app.retrieval.workspace_index import get_workspace_index
from app.services.graph.builder import build_graph


class WorkspaceNotFound(Exception):
    """No workspace with this id is visible to the acting user."""


class SeedNotAnalyzed(Exception):
    """The seed paper has no extracted full text or no ResearchProfile."""


class PaperNotFound(Exception):
    """A referenced paper id does not exist / is not a workspace member."""


class CannotRemoveSeed(Exception):
    """`DELETE .../papers/{seed}` -- the seed cannot be removed."""


@dataclass
class WorkspaceCreateRequest:
    title: str
    seed_paper_id: str
    import_run_id: str | None = None
    token_budget_usd: float = 5.0


def _index_dir(settings: Settings) -> Path:
    return settings.data_dir / "workspace_index"


def _reindex(db: Session, ws: ResearchWorkspace, settings: Settings) -> None:
    idx = get_workspace_index(db, workspace_id=ws.workspace_id, index_dir=_index_dir(settings))
    manifest = idx.rebuild([p.paper_id for p in ws.papers])
    repo.set_workspace_index_path(db, ws.workspace_id, ws.owner_id, manifest.index_path)


def _ranking_snapshot(db: Session, from_run_id: str | None, paper_id: str) -> RankedPaper | None:
    if not from_run_id:
        return None
    pid_to_cid = {pid: cid for cid, pid in repo.get_search_candidate_paper_ids(db, from_run_id).items()}
    cid = pid_to_cid.get(paper_id)
    if cid is None:
        return None
    return next((rp for rp in repo.get_ranked_papers(db, from_run_id) if rp.candidate_id == cid), None)


def _accept_edges_for_target(db: Session, workspace_id: str, owner_id: str, paper_id: str) -> None:
    for edge in repo.get_workspace_trail_edges(db, workspace_id):
        if edge.target_paper_id == paper_id and edge.user_state == UserState.PENDING.value:
            repo.accept_reject_workspace_edge(db, workspace_id, owner_id, edge.edge_id, UserState.ACCEPTED)


def _require_workspace(db: Session, owner: User, workspace_id: str) -> ResearchWorkspace:
    ws = repo.get_workspace(db, workspace_id, owner.id)
    if ws is None:
        raise WorkspaceNotFound(workspace_id)
    return ws


# ---------------------------------------------------------------------------
# Workspace lifecycle
# ---------------------------------------------------------------------------


def create_workspace(
    db: Session, *, owner: User, req: WorkspaceCreateRequest, settings: Settings
) -> ResearchWorkspace:
    seed = repo.get_paper(db, req.seed_paper_id)
    if seed is None:
        raise PaperNotFound(req.seed_paper_id)
    profile = repo.get_profile(db, req.seed_paper_id)
    if not seed.has_full_text or profile is None:
        raise SeedNotAnalyzed(req.seed_paper_id)

    workspace_id = new_id("ws")
    seed_paper = WorkspacePaper(
        workspace_id=workspace_id,
        paper_id=seed.id,
        added_by=AddedBy.MANUAL,
        role=WorkspacePaperRole.SEED,
        grounding=Grounding.FULL_TEXT,
    )
    ws = ResearchWorkspace(
        workspace_id=workspace_id,
        owner_id=owner.id,
        title=req.title,
        seed_paper_id=seed.id,
        seed_profile_id=profile.profile_id,
        token_budget_usd=req.token_budget_usd,
        source_run_id=req.import_run_id,
        papers=[seed_paper],
    )
    repo.create_workspace(db, ws)

    if req.import_run_id and repo.get_search_run(db, req.import_run_id) is not None:
        repo.attach_run_edges_to_workspace(
            db, run_id=req.import_run_id, workspace_id=workspace_id, owner_id=owner.id
        )

    stored = _require_workspace(db, owner, workspace_id)
    _reindex(db, stored, settings)
    return _require_workspace(db, owner, workspace_id)


def get_workspace(db: Session, *, owner: User, workspace_id: str) -> ResearchWorkspace:
    return _require_workspace(db, owner, workspace_id)


def list_workspaces(db: Session, *, owner: User) -> list[ResearchWorkspace]:
    return repo.list_workspaces(db, owner.id)


def update_workspace(
    db: Session,
    *,
    owner: User,
    workspace_id: str,
    title: str | None = None,
    token_budget_usd: float | None = None,
) -> ResearchWorkspace:
    _require_workspace(db, owner, workspace_id)
    updated = repo.update_workspace(
        db, workspace_id, owner.id, title=title, token_budget_usd=token_budget_usd
    )
    assert updated is not None  # ownership already checked
    return updated


def delete_workspace(db: Session, *, owner: User, workspace_id: str) -> None:
    if not repo.delete_workspace(db, workspace_id, owner.id):
        raise WorkspaceNotFound(workspace_id)


# ---------------------------------------------------------------------------
# Paper collection
# ---------------------------------------------------------------------------


def add_papers(
    db: Session,
    *,
    owner: User,
    workspace_id: str,
    paper_ids: list[str],
    from_run_id: str | None = None,
    settings: Settings,
) -> tuple[ResearchWorkspace, list[str]]:
    ws = _require_workspace(db, owner, workspace_id)
    members = {p.paper_id for p in ws.papers}
    added: list[str] = []
    for pid in paper_ids:
        paper = repo.get_paper(db, pid)
        if paper is None:
            raise PaperNotFound(pid)
        if pid in members:
            continue  # idempotent -- a paper appears at most once per workspace
        repo.add_workspace_paper(
            db,
            WorkspacePaper(
                workspace_id=workspace_id,
                paper_id=pid,
                added_by=AddedBy.TRAIL if from_run_id else AddedBy.MANUAL,
                grounding=Grounding.FULL_TEXT if paper.has_full_text else Grounding.ABSTRACT,
                ranking_snapshot=_ranking_snapshot(db, from_run_id, pid),
            ),
            owner.id,
        )
        _accept_edges_for_target(db, workspace_id, owner.id, pid)
        members.add(pid)
        added.append(pid)

    if added:
        _reindex(db, _require_workspace(db, owner, workspace_id), settings)
    return _require_workspace(db, owner, workspace_id), added


def remove_paper(
    db: Session, *, owner: User, workspace_id: str, paper_id: str, settings: Settings
) -> ResearchWorkspace:
    ws = _require_workspace(db, owner, workspace_id)
    member = ws.paper(paper_id)
    if member is None:
        raise PaperNotFound(paper_id)
    if member.role is WorkspacePaperRole.SEED:
        raise CannotRemoveSeed(paper_id)
    repo.remove_workspace_paper(db, workspace_id, paper_id)
    _reindex(db, _require_workspace(db, owner, workspace_id), settings)
    return _require_workspace(db, owner, workspace_id)


def update_paper(
    db: Session, *, owner: User, workspace_id: str, paper_id: str, changes: dict
) -> WorkspacePaper:
    ws = _require_workspace(db, owner, workspace_id)
    if ws.paper(paper_id) is None:
        raise PaperNotFound(paper_id)

    normalised: dict = {}
    if "pinned" in changes:
        normalised["pinned"] = bool(changes["pinned"])
    if "tags" in changes:
        normalised["tags"] = _clean_tags(list(changes["tags"] or []))
    if "note" in changes:
        note = changes["note"]
        normalised["note"] = (note.strip() or None) if isinstance(note, str) else None
    if "order" in changes:
        normalised["order"] = int(changes["order"])

    updated = repo.update_workspace_paper(db, workspace_id, paper_id, normalised)
    assert updated is not None  # membership already checked
    return updated


# ---------------------------------------------------------------------------
# Trail review (Stage S12)
# ---------------------------------------------------------------------------


def grouped_trail(
    db: Session,
    *,
    owner: User,
    workspace_id: str,
    type_filter: str | None = None,
    band: str | None = None,
    state: str | None = None,
) -> dict:
    ws = _require_workspace(db, owner, workspace_id)
    groups: dict[str, list[dict]] = {rt.value: [] for rt in RelationshipType}
    for edge in repo.get_workspace_trail_edges(db, workspace_id):
        if state is None and edge.user_state == UserState.REJECTED.value:
            continue  # rejected edges are hidden unless explicitly asked for
        if state is not None and edge.user_state != state:
            continue
        if type_filter and edge.relationship_type.value != type_filter:
            continue
        if band and edge.confidence.value != band:
            continue
        target = repo.get_paper(db, edge.target_paper_id)
        groups[edge.relationship_type.value].append(
            {
                "target": {
                    "id": edge.target_paper_id,
                    "title": target.title if target else None,
                    "year": target.year if target else None,
                },
                "edge": edge.model_dump(mode="json"),
            }
        )
    return {"seed_paper_id": ws.seed_paper_id, "groups": groups}


def set_edge_state(
    db: Session, *, owner: User, workspace_id: str, edge_id: str, state: UserState
) -> dict:
    _require_workspace(db, owner, workspace_id)
    updated = repo.accept_reject_workspace_edge(db, workspace_id, owner.id, edge_id, state)
    if updated is None:
        raise PaperNotFound(edge_id)  # edge not in this workspace
    return updated.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Research graph (Phase 13)
# ---------------------------------------------------------------------------


def get_graph(db: Session, *, owner: User, workspace_id: str) -> ResearchGraph:
    ws = _require_workspace(db, owner, workspace_id)
    titles: dict[str, str] = {}
    for p in ws.papers:
        paper = repo.get_paper(db, p.paper_id)
        titles[p.paper_id] = paper.title if paper is not None else p.paper_id
    trail_edges = repo.get_workspace_trail_edges(db, workspace_id)
    graph = build_graph(ws, trail_edges, titles)
    repo.set_workspace_graph(db, workspace_id, owner.id, graph)
    return graph


# ---------------------------------------------------------------------------
# Activity (Phase 14): GET /workspaces/{id}/activity reads stage_runs
# ---------------------------------------------------------------------------


def get_activity(
    db: Session, *, owner: User, workspace_id: str, stage: StageName | None = None, limit: int = 50
) -> list[StageRun]:
    _require_workspace(db, owner, workspace_id)
    return repo.list_stage_runs(db, workspace_id, stage=stage, limit=limit)
