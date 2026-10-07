"""The workspace's citation ledger (`GET /workspaces/{id}/citations`).

A read-only view over what the workspace already holds, one entry per
workspace paper:
- its reference, built by the deterministic formatter from the paper's own
  metadata (`metadata_resolver.to_citation` -- never generated);
- what discovery recorded about it: its citation relation to the seed (the
  source run's candidate row) and the trail connections that touch it;
- every place the workspace cites it, each with the passage of *this* paper
  it rests on: chat answers (their verified claims), the latest comparison's
  cells, gaps and directions.
Plus the seed's own bibliography, each entry matched to the paper the trail
resolved it to (a `seed_reference` evidence quote), where one did.

Nothing here is inferred: a use exists only where a stored claim, cell or
evidence span names the paper.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db import repository as repo
from app.domain.chat import ChatRole
from app.domain.gap import GapEvidence
from app.domain.workspace import ResearchWorkspace
from app.services.citations.metadata_resolver import to_citation
from app.services.citations.quote import quote_window

USE_KINDS = ("answer", "comparison", "gap", "direction")


QUOTE_MAX = 700  # as chat shows a passage


def _at(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _evidence_use(kind: str, artefact_id: str, text: str, evidence: GapEvidence, **extra: object) -> dict:
    return {
        "kind": kind,
        "artefact_id": artefact_id,
        "text": text,
        "quote": evidence.span.quote,
        "section": evidence.span.section,
        "page": evidence.span.page,
        "role": evidence.role,
        **extra,
    }


def _uses(db: Session, workspace: ResearchWorkspace, owner_id: str) -> dict[str, list[dict]]:
    uses: dict[str, list[dict]] = {}
    add = lambda pid, use: uses.setdefault(pid, []).append(use)  # noqa: E731

    # chat answers: each verified sentence, with the passage of each paper it cites
    for session in repo.list_chat_sessions(db, workspace.workspace_id, owner_id):
        for message in repo.get_chat_messages(db, session.session_id):
            if message.role is not ChatRole.ASSISTANT:
                continue
            for claim in repo.get_claims_for_artefact(db, message.message_id):
                chunks = repo.get_chunks_by_ids(db, list(claim.supporting_chunk_ids))
                for pid in dict.fromkeys(claim.supporting_paper_ids):
                    chunk = next((c for c in chunks if c.paper_id == pid), None)
                    # the part of the passage that supports the sentence, verbatim, with it marked
                    window = quote_window(chunk.text, claim.sentence, max_chars=QUOTE_MAX) if chunk else None
                    add(pid, {
                        "kind": "answer", "artefact_id": message.message_id, "text": claim.sentence,
                        "quote": window.quote if window else None,
                        "cut_before": window.cut_before if window else False,
                        "cut_after": window.cut_after if window else False,
                        "highlight": list(window.highlight) if window and window.highlight else None,
                        "section": chunk.section if chunk else None,
                        "page": chunk.page if chunk else None, "session_id": session.session_id,
                        "created_at": _at(message.created_at),
                    })

    # the comparison on screen (the latest), cell by cell
    comparisons = repo.list_comparisons(db, workspace.workspace_id)
    if comparisons:
        latest = comparisons[0]
        for row in latest.rows:
            for field, cell in row.cells.items():
                if cell.text is None or cell.span is None:
                    continue
                add(row.paper_id, {
                    "kind": "comparison", "artefact_id": latest.comparison_id, "field": field, "text": cell.text,
                    "quote": cell.span.quote, "section": cell.span.section, "page": cell.span.page,
                    "created_at": _at(latest.created_at),
                })

    for gap in repo.get_gaps(db, workspace.workspace_id):
        for pid in dict.fromkeys(e.paper_id for e in [*gap.supporting_evidence, *gap.conflicting_evidence]):
            ev = next(e for e in [*gap.supporting_evidence, *gap.conflicting_evidence] if e.paper_id == pid)
            add(pid, _evidence_use("gap", gap.gap_id, gap.statement, ev, state=gap.user_state, created_at=_at(gap.generated_at)))

    for d in repo.get_directions(db, workspace.workspace_id):
        for pid in dict.fromkeys(e.paper_id for e in d.supporting_evidence):
            ev = next(e for e in d.supporting_evidence if e.paper_id == pid)
            add(pid, _evidence_use("direction", d.direction_id, d.proposal, ev, state=d.user_state, gap_id=d.gap_id, created_at=_at(d.generated_at)))

    order = {k: i for i, k in enumerate(USE_KINDS)}
    for items in uses.values():
        items.sort(key=lambda u: u.get("created_at") or "", reverse=True)
        items.sort(key=lambda u: order[u["kind"]])
    return uses


def build_ledger(db: Session, workspace: ResearchWorkspace, *, owner_id: str) -> dict:
    members = [wp.paper_id for wp in workspace.papers]
    ordered = [workspace.seed_paper_id, *[p for p in members if p != workspace.seed_paper_id]] if workspace.seed_paper_id in members else members

    relation = repo.get_run_citation_relationships(db, workspace.source_run_id) if workspace.source_run_id else {}

    edges = [e for e in repo.get_workspace_trail_edges(db, workspace.workspace_id) if e.user_state != "rejected"]
    uses = _uses(db, workspace, owner_id)

    papers: list[dict] = []
    for number, pid in enumerate(ordered, start=1):
        paper = repo.get_paper(db, pid)
        if paper is None:
            continue
        citation = to_citation(workspace.workspace_id, paper, number=number)
        own = uses.get(pid, [])
        papers.append({
            "paper_id": pid,
            "title": paper.title,
            "authors": list(paper.authors or []),
            "year": paper.year,
            "venue": paper.venue,
            "publisher": paper.publisher,
            "doi": paper.doi,
            "arxiv_id": paper.arxiv_id,
            "url": paper.url,
            "role": "seed" if pid == workspace.seed_paper_id else "member",
            "grounding": "full_text" if paper.has_full_text else "abstract",
            "reference": {"resolved_from": citation.resolved_from, "formatted": citation.formatted},
            "reference_count": len(paper.references or []) if paper.has_full_text else None,
            "seed_relation": None if pid == workspace.seed_paper_id else relation.get(pid),
            "connections": [
                {
                    "edge_id": e.edge_id,
                    "type": e.relationship_type.value,
                    "other_paper_id": e.target_paper_id if e.source_paper_id == pid else e.source_paper_id,
                    "direction": "out" if e.source_paper_id == pid else "in",
                    "state": e.user_state,
                }
                for e in edges
                if pid in (e.source_paper_id, e.target_paper_id)
            ],
            "uses": own,
            "counts": {k: sum(1 for u in own if u["kind"] == k) for k in USE_KINDS},
        })

    # the seed's bibliography, each entry matched through the trail's own seed_reference evidence
    resolved: dict[str, str] = {}
    for e in edges:
        for ev in e.evidence:
            if ev.role == "seed_reference" and ev.span.paper_id == workspace.seed_paper_id:
                resolved.setdefault(ev.span.quote, e.target_paper_id if e.source_paper_id == workspace.seed_paper_id else e.source_paper_id)
    seed = repo.get_paper(db, workspace.seed_paper_id)
    seed_references: list[dict] = []
    for ref in (seed.references or []) if seed else []:
        text = str(ref.get("raw_text", ""))
        match = next((p for q, p in resolved.items() if q and (text == q or text.startswith(q))), None)
        seed_references.append({"order": ref.get("order", len(seed_references)), "text": text, "paper_id": match, "in_workspace": match in members})

    return {"workspace_id": workspace.workspace_id, "papers": papers, "seed_references": seed_references}
