"""A research trail between a workspace's own papers and its seed
(remediation, 2026-10-02).

A trail used to come only from a discovery run: a workspace whose papers the
reader uploaded or added by hand had none, and its trail sent them to
discovery instead. Now the workspace's papers are connected the same way a
run's candidates are: each is scored against the seed with discovery's own
signals (semantic similarity of the two papers and their passages, the
seed's research problem, methods and datasets, citation links, recency),
and the trail's rules type each connection from those signals and the
papers' own words. Citation links come from the papers' reference lists:
the seed citing a member, or a member citing the seed.

One trail run per workspace, rebuilt in place: decisions the reader made
are kept (an accepted connection stays accepted, a rejected one is never
proposed again).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.domain.candidate import CitationRelationship, SearchRun
from app.domain.workspace import ResearchWorkspace
from app.retrieval.embeddings import discovery_embedder
from app.services.ranking.pipeline import RankOptions, rank_search_run
from app.services.trail.evidence import seed_reference_span
from app.services.trail.pipeline import TrailOptions, build_trail

RUN_KIND = "workspace_papers"


class NothingToConnect(Exception):
    """The workspace holds only its seed."""


@dataclass(frozen=True)
class WorkspaceTrailResult:
    run_id: str
    papers: int
    ranked: int
    edges: int
    connected_papers: int
    unconnected_papers: int


def workspace_run_id(workspace_id: str) -> str:
    return f"run_wsp_{workspace_id.removeprefix('ws_')}"


def _citation_relation(seed: PaperORM, member: PaperORM) -> CitationRelationship:
    """From the papers' own reference lists: the seed lists the member, or
    the member lists the seed."""
    if seed_reference_span(seed.id, member.title, list(seed.references or [])) is not None:
        return CitationRelationship.CITED_BY_SEED
    if seed_reference_span(member.id, seed.title, list(member.references or [])) is not None:
        return CitationRelationship.CITES_SEED
    return CitationRelationship.NONE


async def build_workspace_trail(
    db: Session, *, workspace: ResearchWorkspace, owner_id: str, settings: Settings
) -> WorkspaceTrailResult:
    seed = repo.get_paper(db, workspace.seed_paper_id)
    members = [p.paper_id for p in workspace.papers if p.paper_id != workspace.seed_paper_id]
    if seed is None or not members:
        raise NothingToConnect(workspace.workspace_id)

    run_id = workspace_run_id(workspace.workspace_id)
    if repo.get_search_run(db, run_id) is None:
        repo.create_search_run(
            db,
            SearchRun(
                run_id=run_id,
                owner_id=owner_id,
                workspace_id=workspace.workspace_id,
                seed_paper_id=seed.id,
                report={"kind": RUN_KIND},
            ),
        )
    else:
        repo.reset_run_candidates(db, run_id)

    for i, pid in enumerate(members):
        member = repo.get_paper(db, pid)
        if member is None:
            continue
        repo.add_search_candidate(
            db,
            candidate_id=f"cand_{run_id.removeprefix('run_')}_{i}",
            run_id=run_id,
            paper_id=pid,
            discovery_methods=[],
            possible_duplicate_of=None,
            provenance={"source": RUN_KIND},
            citation_relationship=_citation_relation(seed, member),
            commit=False,
        )
    db.commit()

    embedder = discovery_embedder(settings.discovery_embedder, model_dir=Path(settings.data_dir) / "models")
    # every paper here was chosen by the reader: none is dropped as off-topic
    ranked = await rank_search_run(
        db,
        run_id=run_id,
        settings=settings,
        options=RankOptions(chunk_embedder=embedder, doc_embedder=embedder, min_relevance=None),
    )
    trail = await build_trail(db, run_id=run_id, settings=settings, options=TrailOptions(embedder=embedder, top_k=len(members)))
    repo.attach_run_edges_to_workspace(db, run_id=run_id, workspace_id=workspace.workspace_id, owner_id=owner_id)
    return WorkspaceTrailResult(
        run_id=run_id,
        papers=len(members),
        ranked=ranked.ranked_count,
        edges=trail.edge_count,
        connected_papers=trail.typed_targets,
        unconnected_papers=trail.unknown_targets,
    )
