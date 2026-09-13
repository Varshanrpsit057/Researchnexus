"""The orchestrator's CITATIONS stage entry point (Roadmap Phase 14).

Mirrors `routers/synthesis.py::citations` exactly (same target/format
resolution, same per-paper loop, same response shape) so the orchestrator
can wrap it with `stage_runs` telemetry without duplicating that endpoint's
behaviour under a second, drifting implementation. The router keeps its
own inline loop -- this module exists so the orchestrator has a single
callable to log, not to replace the router.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db import repository as repo
from app.domain.workspace import ResearchWorkspace
from app.services.citations.metadata_resolver import to_citation

_KNOWN_FORMATS = {"apa", "ieee", "bibtex"}


@dataclass
class CitationsBuildResult:
    citations: list[dict] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def build_citations(
    db: Session, *, workspace: ResearchWorkspace, paper_ids: list[str] | None, formats: list[str], owner_id: str
) -> CitationsBuildResult:
    member_ids = [p.paper_id for p in workspace.papers]
    if paper_ids:
        wanted = set(paper_ids)
        targets = [pid for pid in member_ids if pid in wanted]
    else:
        targets = member_ids

    kept_formats = [f for f in formats if f in _KNOWN_FORMATS] or sorted(_KNOWN_FORMATS)
    result = CitationsBuildResult()
    for i, pid in enumerate(targets, start=1):
        paper = repo.get_paper(db, pid)
        if paper is None:
            result.unresolved.append(pid)
            continue
        citation = to_citation(workspace.workspace_id, paper, number=i)
        repo.upsert_citation(db, citation, owner_id=owner_id)
        result.citations.append(
            {
                "paper_id": pid,
                "resolved_from": citation.resolved_from,
                "formatted": {f: citation.formatted.get(f, "Not available") for f in kept_formats},
            }
        )
        if citation.resolved_from == "unresolved":
            result.unresolved.append(pid)
    return result
