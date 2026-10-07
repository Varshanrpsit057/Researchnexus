"""A reader's paper library (remediation, 2026-10-06).

Papers belong to no one -- one PDF is one paper, whoever uploads it, and
discovery's papers are shared -- so a reader's library is assembled from the
records that do say who did what: the uploads they made (ingest jobs), the
papers they analysed (profiles), the papers they searched from (discovery
runs) and the papers in their workspaces. Each paper says how it got there,
which workspaces hold it, what text it is read from and whether it has a
research profile, newest activity first.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    JobORM,
    PaperORM,
    ResearchProfileORM,
    SearchRunORM,
    WorkspaceORM,
    WorkspacePaperORM,
)
from app.domain.jobs import JobKind, JobStatus
from app.services.fulltext.retrieve import coverage_of

# how a paper got into the library, in the order they are listed
ROLES = ("uploaded", "seed", "searched", "analyzed", "collected")
_CHUNK = 500  # ids per IN (...) -- well under SQLite's variable limit
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class _Entry:
    roles: set[str] = field(default_factory=set)
    workspaces: dict[str, str] = field(default_factory=dict)
    last_run_id: str | None = None
    last_run_at: datetime | None = None
    last_active_at: datetime = _EPOCH

    def touch(self, role: str, at: datetime | None) -> None:
        self.roles.add(role)
        if at is not None and at > self.last_active_at:
            self.last_active_at = at


def _chunks(ids: list[str]) -> Iterator[list[str]]:
    for i in range(0, len(ids), _CHUNK):
        yield ids[i : i + _CHUNK]


def _collect(db: Session, owner_id: str) -> tuple[dict[str, _Entry], int, int]:
    entries: dict[str, _Entry] = {}

    def entry(pid: str) -> _Entry:
        return entries.setdefault(pid, _Entry())

    uploads = db.execute(
        select(JobORM.result_ref, JobORM.created_at).where(
            JobORM.owner_id == owner_id,
            JobORM.kind == JobKind.INGEST.value,
            JobORM.status == JobStatus.SUCCEEDED.value,
            JobORM.result_ref.is_not(None),
        )
    )
    for pid, at in uploads:
        entry(pid).touch("uploaded", at)

    analysed = db.execute(
        select(ResearchProfileORM.paper_id, ResearchProfileORM.updated_at).where(ResearchProfileORM.owner_id == owner_id)
    )
    for pid, at in analysed:
        entry(pid).touch("analyzed", at)

    runs = db.execute(
        select(SearchRunORM.seed_paper_id, SearchRunORM.id, SearchRunORM.started_at).where(SearchRunORM.owner_id == owner_id)
    ).all()
    for pid, run_id, at in runs:
        e = entry(pid)
        e.touch("searched", at)
        if e.last_run_at is None or (at is not None and at > e.last_run_at):
            e.last_run_id, e.last_run_at = run_id, at

    titles: dict[str, str] = {
        ws_id: title for ws_id, title in db.execute(select(WorkspaceORM.id, WorkspaceORM.title).where(WorkspaceORM.owner_id == owner_id))
    }
    members = db.execute(
        select(WorkspacePaperORM.paper_id, WorkspacePaperORM.workspace_id, WorkspacePaperORM.role, WorkspacePaperORM.added_at).where(
            WorkspacePaperORM.owner_id == owner_id
        )
    )
    for pid, ws_id, role, at in members:
        if ws_id not in titles:
            continue
        e = entry(pid)
        e.touch("seed" if role == "seed" else "collected", at)
        e.workspaces[ws_id] = titles[ws_id]

    # discovery runs and workspaces are counted, not only listed: a run's seed may repeat
    return entries, len(runs), len(titles)


def _with_profiles(db: Session, ids: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for chunk in _chunks(list(ids)):
        out.update(db.execute(select(ResearchProfileORM.paper_id).where(ResearchProfileORM.paper_id.in_(chunk))).scalars())
    return out


def build_library(db: Session, owner_id: str) -> dict[str, object]:
    entries, run_count, workspace_count = _collect(db, owner_id)
    papers: dict[str, PaperORM] = {}
    for chunk in _chunks(list(entries)):
        papers.update({p.id: p for p in db.execute(select(PaperORM).where(PaperORM.id.in_(chunk))).scalars()})
    profiled = _with_profiles(db, papers)

    rows: list[dict[str, object]] = []
    for pid, paper in papers.items():
        e = entries[pid]
        rows.append(
            {
                "id": pid,
                "title": paper.title,
                "authors": list(paper.authors or []),
                "year": paper.year,
                "venue": paper.venue,
                "publisher": paper.publisher,
                "doi": paper.doi,
                "source": paper.source,
                "has_abstract": bool((paper.abstract or "").strip()),
                "has_full_text": paper.has_full_text,
                "coverage": coverage_of(paper),
                "analyzed": pid in profiled,
                "roles": [r for r in ROLES if r in e.roles],
                "workspaces": [{"workspace_id": w, "title": t} for w, t in sorted(e.workspaces.items(), key=lambda kv: kv[1].lower())],
                "last_run_id": e.last_run_id,
                "last_active_at": e.last_active_at.isoformat(),
            }
        )
    rows.sort(key=lambda r: (str(r["title"]).lower()))
    rows.sort(key=lambda r: str(r["last_active_at"]), reverse=True)
    return {
        "papers": rows,
        "counts": {
            "papers": len(rows),
            "uploaded": sum("uploaded" in r["roles"] for r in rows),  # type: ignore[operator]
            "analyzed": sum(bool(r["analyzed"]) for r in rows),
            "in_workspaces": sum(bool(r["workspaces"]) for r in rows),
            "discovery_runs": run_count,
            "workspaces": workspace_count,
        },
    }

