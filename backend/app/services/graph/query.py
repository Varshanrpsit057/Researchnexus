"""Read-only ResearchGraph query/serialization interface (Roadmap Phase 13:
"graph serialization/query interface... foundation for later GraphRAG/theme
queries").

Deliberately minimal: id lookup, type filters, and undirected adjacency --
enough for a caller to inspect or render the graph. No scoring, ranking, or
path-finding here; that is GraphRAG routing (explicitly out of scope for
this phase) and belongs behind this same interface later, not inside it.
"""

from __future__ import annotations

from app.domain.graph import GraphEdge, GraphEdgeType, GraphNode, GraphNodeType, ResearchGraph


class GraphQuery:
    def __init__(self, graph: ResearchGraph) -> None:
        self._graph = graph
        self._nodes_by_id = {n.id: n for n in graph.nodes}

    @property
    def graph(self) -> ResearchGraph:
        return self._graph

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes_by_id.get(node_id)

    def nodes_by_type(self, node_type: GraphNodeType) -> list[GraphNode]:
        return [n for n in self._graph.nodes if n.type is node_type]

    def edges_of_type(self, edge_type: GraphEdgeType) -> list[GraphEdge]:
        return [e for e in self._graph.edges if e.type is edge_type]

    def neighbors(self, node_id: str) -> list[str]:
        found: set[str] = set()
        for e in self._graph.edges:
            if e.src == node_id:
                found.add(e.dst)
            elif e.dst == node_id:
                found.add(e.src)
        found.discard(node_id)
        return sorted(found)

    def to_json(self) -> dict:
        return self._graph.model_dump(mode="json")

    @classmethod
    def from_json(cls, data: dict) -> GraphQuery:
        return cls(ResearchGraph.model_validate(data))
