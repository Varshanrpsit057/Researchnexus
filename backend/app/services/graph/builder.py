"""Deterministic ResearchGraph projection (Architecture §5 `GraphBuilder`;
Roadmap Phase 13).

Phase 13 populates only what the workspace already has verified: a `PAPER`
node for every workspace member and a graph edge for every non-rejected
Phase 7 `TrailEdge` whose endpoints are both still workspace members. No
node or edge is ever invented -- richer projections (methods/datasets/
topics/questions from profiles; gaps/directions) are foundation-only this
phase (the full `GraphNodeType` / `GraphEdgeType` vocabulary is already
fixed in app/domain/graph.py for those later phases to populate).

`RelationshipType -> GraphEdgeType` is a fixed, total mapping grounded in
what each trail rule actually detects (app/services/trail/rules.py):
FOUNDATIONAL and METHOD_EXTENSION are citation facts (-> CITES / EXTENDS);
RECENT is a topical-similarity signal with no citation, same family as the
base SIMILAR rule (-> SIMILAR); COMPETING, DATASET_RELATED and
POTENTIALLY_CONTRADICTORY map onto their same-meaning graph types.

Two trail edges that collapse onto the same `(src, dst, type)` after this
mapping (e.g. SIMILAR and RECENT between the same pair) are merged into one
graph edge: evidence spans are unioned (deduplicated by paper+quote) and the
higher of the two confidences is kept -- never dropped, never duplicated.
"""

from __future__ import annotations

from app.domain.graph import GraphEdge, GraphEdgeType, GraphNode, GraphNodeType, ResearchGraph
from app.domain.profile import Confidence, SourceSpan
from app.domain.trail import RelationshipType, TrailEdge
from app.domain.workspace import ResearchWorkspace

_EDGE_TYPE_MAP: dict[RelationshipType, GraphEdgeType] = {
    RelationshipType.SIMILAR: GraphEdgeType.SIMILAR,
    RelationshipType.FOUNDATIONAL: GraphEdgeType.CITES,
    RelationshipType.RECENT: GraphEdgeType.SIMILAR,
    RelationshipType.COMPETING: GraphEdgeType.COMPETES_WITH,
    RelationshipType.METHOD_EXTENSION: GraphEdgeType.EXTENDS,
    RelationshipType.DATASET_RELATED: GraphEdgeType.USES_DATASET,
    RelationshipType.POTENTIALLY_CONTRADICTORY: GraphEdgeType.CONTRADICTS,
}

_CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


def _higher_confidence(a: Confidence, b: Confidence) -> Confidence:
    return a if _CONFIDENCE_RANK[a] >= _CONFIDENCE_RANK[b] else b


def _dedupe_spans(spans: list[SourceSpan]) -> list[SourceSpan]:
    seen: set[tuple[str, str]] = set()
    out: list[SourceSpan] = []
    for span in spans:
        key = (span.paper_id, span.quote)
        if key in seen:
            continue
        seen.add(key)
        out.append(span)
    return out


def build_graph(
    workspace: ResearchWorkspace, trail_edges: list[TrailEdge], paper_titles: dict[str, str]
) -> ResearchGraph:
    """Pure projection: workspace papers + non-rejected trail edges -> graph.

    `paper_titles` is a `paper_id -> title` lookup for node labels; a paper
    with no entry falls back to its id. Deterministic: sorting every input
    before folding it in means the result never depends on caller order.
    """
    member_ids = {p.paper_id for p in workspace.papers}
    nodes = [
        GraphNode(
            id=p.paper_id,
            type=GraphNodeType.PAPER,
            label=paper_titles.get(p.paper_id, p.paper_id),
            paper_ids=[p.paper_id],
        )
        for p in sorted(workspace.papers, key=lambda p: p.paper_id)
    ]

    merged: dict[tuple[str, str, GraphEdgeType], GraphEdge] = {}
    ordered_edges = sorted(trail_edges, key=lambda e: (e.target_paper_id, e.relationship_type.value, e.edge_id))
    for edge in ordered_edges:
        if edge.user_state == "rejected":
            continue
        if edge.source_paper_id not in member_ids or edge.target_paper_id not in member_ids:
            continue  # the paper left the workspace; the trail row is stale
        gtype = _EDGE_TYPE_MAP[edge.relationship_type]
        key = (edge.source_paper_id, edge.target_paper_id, gtype)
        spans = [ev.span for ev in edge.evidence]
        existing = merged.get(key)
        if existing is None:
            merged[key] = GraphEdge(
                src=edge.source_paper_id, dst=edge.target_paper_id, type=gtype, evidence=spans, confidence=edge.confidence
            )
        else:
            merged[key] = existing.model_copy(
                update={
                    "evidence": _dedupe_spans(existing.evidence + spans),
                    "confidence": _higher_confidence(existing.confidence, edge.confidence),
                }
            )

    edges = [merged[key] for key in sorted(merged.keys())]
    return ResearchGraph(workspace_id=workspace.workspace_id, nodes=nodes, edges=edges)
