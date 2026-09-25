"""Deterministic ResearchGraph projection (Architecture §5 `GraphBuilder`;
Roadmap Phase 13).

The graph shows what the workspace already has verified: a `PAPER` node for
every workspace member, and a graph edge for every non-rejected Phase 7
`TrailEdge` attached to the workspace. A trail edge's far end need not be a
member -- importing a discovery run attaches its edges before any of its
papers are added, and accepting an edge in the trail review does not add the
paper -- so such a paper gets a node of its own, flagged `in_workspace=False`
("connected"), rather than the edge silently vanishing. A paper that left the
workspace while its trail edge still stands is likewise shown as connected;
rejecting the edge is what removes it. No node or edge is ever invented:
every connected node is an endpoint of a real trail edge. Richer projections
(methods/datasets/topics/questions from profiles; gaps/directions) are
foundation-only (the full `GraphNodeType` / `GraphEdgeType` vocabulary is
already fixed in app/domain/graph.py for those later phases to populate).

`RelationshipType -> GraphEdgeType` is a fixed, total mapping grounded in
what each trail rule actually detects (app/services/trail/rules.py):
FOUNDATIONAL and METHOD_EXTENSION are citation facts (-> CITES / EXTENDS);
RECENT is a topical-similarity signal with no citation, same family as the
base SIMILAR rule (-> SIMILAR); COMPETING, DATASET_RELATED and
POTENTIALLY_CONTRADICTORY map onto their same-meaning graph types.

Two trail edges that collapse onto the same `(src, dst, type)` after this
mapping (e.g. SIMILAR and RECENT between the same pair) are merged into one
graph edge: evidence spans are unioned (deduplicated by paper+quote), the
higher of the two confidences is kept, both trail edge ids and relationship
types are listed, and the merged edge stays PENDING while either still
awaits review -- never dropped, never duplicated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.domain.graph import GraphEdge, GraphEdgeType, GraphNode, GraphNodeType, ResearchGraph
from app.domain.profile import Confidence, SourceSpan
from app.domain.trail import RelationshipType, TrailEdge, UserState
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


@dataclass(frozen=True)
class PaperDetails:
    """Bibliographic facts a paper node carries, from the papers table."""

    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None


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


def _state(user_state: str) -> UserState:
    return UserState.PENDING if user_state == UserState.PENDING.value else UserState.ACCEPTED


def build_graph(
    workspace: ResearchWorkspace,
    trail_edges: list[TrailEdge],
    paper_titles: Mapping[str, str],
    paper_details: Mapping[str, PaperDetails] | None = None,
) -> ResearchGraph:
    """Pure projection: workspace papers + non-rejected trail edges -> graph.

    `paper_titles` is a `paper_id -> title` lookup for node labels; a paper
    with no entry falls back to its id. `paper_details` adds year / authors /
    venue where known. Deterministic: sorting every input before folding it
    in means the result never depends on caller order.
    """
    details = paper_details or {}
    members = {p.paper_id: p for p in workspace.papers}
    live_edges = sorted(
        (e for e in trail_edges if e.user_state != UserState.REJECTED.value),
        key=lambda e: (e.target_paper_id, e.relationship_type.value, e.edge_id),
    )
    connected = {pid for e in live_edges for pid in (e.source_paper_id, e.target_paper_id)} - members.keys()

    def node(paper_id: str) -> GraphNode:
        member = members.get(paper_id)
        info = details.get(paper_id, PaperDetails())
        return GraphNode(
            id=paper_id,
            type=GraphNodeType.PAPER,
            label=paper_titles.get(paper_id, paper_id),
            paper_ids=[paper_id],
            in_workspace=member is not None,
            role=member.role if member is not None else None,
            year=info.year,
            authors=list(info.authors),
            venue=info.venue,
        )

    # members first, then connected papers; each in id order
    nodes = [node(pid) for pid in sorted(members)] + [node(pid) for pid in sorted(connected)]

    merged: dict[tuple[str, str, GraphEdgeType], GraphEdge] = {}
    for edge in live_edges:
        gtype = _EDGE_TYPE_MAP[edge.relationship_type]
        key = (edge.source_paper_id, edge.target_paper_id, gtype)
        spans = [ev.span for ev in edge.evidence]
        existing = merged.get(key)
        if existing is None:
            merged[key] = GraphEdge(
                src=edge.source_paper_id,
                dst=edge.target_paper_id,
                type=gtype,
                evidence=_dedupe_spans(spans),
                confidence=edge.confidence,
                trail_edge_ids=[edge.edge_id],
                relationship_types=[edge.relationship_type],
                user_state=_state(edge.user_state),
            )
        else:
            pending = UserState.PENDING in (existing.user_state, _state(edge.user_state))
            merged[key] = existing.model_copy(
                update={
                    "evidence": _dedupe_spans(existing.evidence + spans),
                    "confidence": _higher_confidence(existing.confidence, edge.confidence),
                    "trail_edge_ids": [*existing.trail_edge_ids, edge.edge_id],
                    "relationship_types": sorted(
                        {*existing.relationship_types, edge.relationship_type}, key=lambda t: t.value
                    ),
                    "user_state": UserState.PENDING if pending else UserState.ACCEPTED,
                }
            )

    edges = [merged[key] for key in sorted(merged.keys())]
    return ResearchGraph(workspace_id=workspace.workspace_id, nodes=nodes, edges=edges)
