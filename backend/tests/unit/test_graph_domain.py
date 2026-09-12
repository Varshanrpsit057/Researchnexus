from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.graph import GraphEdge, GraphEdgeType, GraphNode, GraphNodeType, ResearchGraph
from app.domain.profile import Confidence, SourceSpan


def _node(node_id: str = "pap_1") -> GraphNode:
    return GraphNode(id=node_id, type=GraphNodeType.PAPER, label="A Paper", paper_ids=[node_id])


def _edge(src: str = "pap_1", dst: str = "pap_2") -> GraphEdge:
    return GraphEdge(
        src=src,
        dst=dst,
        type=GraphEdgeType.SIMILAR,
        evidence=[SourceSpan(paper_id=dst, quote="a supporting sentence")],
        confidence=Confidence.MEDIUM,
    )


def test_all_eight_node_types_are_defined() -> None:
    assert {t.value for t in GraphNodeType} == {
        "PAPER", "METHOD", "DATASET", "TOPIC", "RESEARCH_QUESTION", "CLAIM", "GAP", "DIRECTION",
    }


def test_all_ten_edge_types_are_defined() -> None:
    assert {t.value for t in GraphEdgeType} == {
        "SIMILAR", "CITES", "EXTENDS", "USES_METHOD", "USES_DATASET",
        "COMPETES_WITH", "SUPPORTS", "CONTRADICTS", "ADDRESSES", "EXPOSES_GAP",
    }


def test_graph_node_requires_a_type_from_the_enum() -> None:
    with pytest.raises(ValidationError):
        GraphNode(id="x", type="NOT_A_TYPE", label="x")  # type: ignore[arg-type]


def test_graph_edge_requires_a_type_from_the_enum() -> None:
    with pytest.raises(ValidationError):
        GraphEdge(src="a", dst="b", type="NOT_A_TYPE", confidence=Confidence.LOW)  # type: ignore[arg-type]


def test_node_and_edge_counts_are_derived_not_freely_settable() -> None:
    g = ResearchGraph(
        workspace_id="ws_1",
        nodes=[_node("pap_1"), _node("pap_2")],
        edges=[_edge("pap_1", "pap_2")],
        node_count=999,  # any input value is ignored -- always derived from len(nodes/edges)
        edge_count=999,
    )
    assert g.node_count == 2
    assert g.edge_count == 1


def test_empty_graph_has_zero_counts() -> None:
    g = ResearchGraph(workspace_id="ws_1")
    assert g.node_count == 0
    assert g.edge_count == 0
    assert g.nodes == []
    assert g.edges == []


def test_graph_round_trips_through_json() -> None:
    g = ResearchGraph(workspace_id="ws_1", nodes=[_node()], edges=[])
    dumped = g.model_dump(mode="json")
    restored = ResearchGraph.model_validate(dumped)
    assert restored == g
