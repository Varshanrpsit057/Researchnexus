from __future__ import annotations

from app.domain.graph import GraphEdge, GraphEdgeType, GraphNode, GraphNodeType, ResearchGraph
from app.domain.profile import Confidence, SourceSpan
from app.services.graph.query import GraphQuery


def _graph() -> ResearchGraph:
    nodes = [
        GraphNode(id="pap_seed", type=GraphNodeType.PAPER, label="Seed", paper_ids=["pap_seed"]),
        GraphNode(id="pap_a", type=GraphNodeType.PAPER, label="A", paper_ids=["pap_a"]),
        GraphNode(id="pap_b", type=GraphNodeType.PAPER, label="B", paper_ids=["pap_b"]),
    ]
    edges = [
        GraphEdge(
            src="pap_seed", dst="pap_a", type=GraphEdgeType.SIMILAR,
            evidence=[SourceSpan(paper_id="pap_a", quote="q1")], confidence=Confidence.MEDIUM,
        ),
        GraphEdge(
            src="pap_seed", dst="pap_b", type=GraphEdgeType.COMPETES_WITH,
            evidence=[SourceSpan(paper_id="pap_b", quote="q2")], confidence=Confidence.HIGH,
        ),
    ]
    return ResearchGraph(workspace_id="ws_1", nodes=nodes, edges=edges)


def test_node_looks_up_by_id() -> None:
    q = GraphQuery(_graph())
    assert q.node("pap_a") is not None
    assert q.node("pap_a").label == "A"  # type: ignore[union-attr]
    assert q.node("does_not_exist") is None


def test_nodes_by_type_filters() -> None:
    q = GraphQuery(_graph())
    assert len(q.nodes_by_type(GraphNodeType.PAPER)) == 3
    assert q.nodes_by_type(GraphNodeType.GAP) == []


def test_edges_of_type_filters() -> None:
    q = GraphQuery(_graph())
    similar = q.edges_of_type(GraphEdgeType.SIMILAR)
    assert len(similar) == 1
    assert similar[0].dst == "pap_a"


def test_neighbors_are_undirected_and_exclude_self() -> None:
    q = GraphQuery(_graph())
    assert q.neighbors("pap_seed") == ["pap_a", "pap_b"]
    assert q.neighbors("pap_a") == ["pap_seed"]
    assert q.neighbors("pap_missing") == []


def test_to_json_and_from_json_round_trip() -> None:
    g = _graph()
    q = GraphQuery(g)
    restored = GraphQuery.from_json(q.to_json())
    assert restored.to_json() == q.to_json()
    assert restored.node("pap_a") is not None
