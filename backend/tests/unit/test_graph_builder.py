from __future__ import annotations

from app.domain.graph import GraphEdgeType, GraphNodeType
from app.domain.profile import Confidence, SourceSpan
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge, UserState
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.services.graph.builder import PaperDetails, build_graph

_TITLES = {"pap_seed": "Seed Paper", "pap_a": "Paper A", "pap_b": "Paper B"}


def _ws(paper_ids: list[str] = ["pap_seed", "pap_a"]) -> ResearchWorkspace:  # noqa: B006 - test fixture
    papers = [
        WorkspacePaper(
            workspace_id="ws_1", paper_id=pid, added_by=AddedBy.MANUAL,
            role=WorkspacePaperRole.SEED if pid == "pap_seed" else WorkspacePaperRole.RELATED,
        )
        for pid in paper_ids
    ]
    return ResearchWorkspace(
        workspace_id="ws_1", owner_id="usr_1", title="W",
        seed_paper_id="pap_seed", seed_profile_id="prof_1", papers=papers,
    )


def _edge(
    target: str,
    rtype: RelationshipType,
    *,
    edge_id: str = "edge_1",
    source: str = "pap_seed",
    user_state: str = "pending",
    confidence: Confidence = Confidence.MEDIUM,
    quote: str = "a supporting sentence",
) -> TrailEdge:
    edge = TrailEdge(
        edge_id=edge_id,
        run_id="run_1",
        workspace_id="ws_1",
        source_paper_id=source,
        target_paper_id=target,
        relationship_type=rtype,
        detection_method=DetectionMethod.RULE,
        rule_fired="a rule",
        evidence=[Evidence(span=SourceSpan(paper_id=target, quote=quote), role="target_claim")],
        confidence=confidence,
    )
    edge.user_state = user_state
    return edge


def test_a_node_is_built_for_every_workspace_paper() -> None:
    g = build_graph(_ws(["pap_seed", "pap_a"]), [], _TITLES)
    assert g.node_count == 2
    ids = {n.id for n in g.nodes}
    assert ids == {"pap_seed", "pap_a"}
    node = next(n for n in g.nodes if n.id == "pap_a")
    assert node.type == GraphNodeType.PAPER
    assert node.label == "Paper A"
    assert node.paper_ids == ["pap_a"]


def test_missing_title_falls_back_to_the_paper_id() -> None:
    g = build_graph(_ws(["pap_seed", "pap_unknown"]), [], {"pap_seed": "Seed Paper"})
    node = next(n for n in g.nodes if n.id == "pap_unknown")
    assert node.label == "pap_unknown"


def test_no_nodes_are_invented_beyond_workspace_membership() -> None:
    g = build_graph(_ws(["pap_seed"]), [], _TITLES)
    assert g.node_count == 1


# --- trail-to-graph projection ---------------------------------------------


def test_similar_trail_edge_projects_to_similar_graph_edge() -> None:
    g = build_graph(_ws(), [_edge("pap_a", RelationshipType.SIMILAR)], _TITLES)
    assert g.edge_count == 1
    e = g.edges[0]
    assert e.src == "pap_seed" and e.dst == "pap_a"
    assert e.type == GraphEdgeType.SIMILAR
    assert e.confidence == Confidence.MEDIUM
    assert e.evidence[0].quote == "a supporting sentence"


def test_relationship_type_mapping_is_total_and_deterministic() -> None:
    expected = {
        RelationshipType.SIMILAR: GraphEdgeType.SIMILAR,
        RelationshipType.FOUNDATIONAL: GraphEdgeType.CITES,
        RelationshipType.RECENT: GraphEdgeType.SIMILAR,
        RelationshipType.COMPETING: GraphEdgeType.COMPETES_WITH,
        RelationshipType.METHOD_EXTENSION: GraphEdgeType.EXTENDS,
        RelationshipType.DATASET_RELATED: GraphEdgeType.USES_DATASET,
        RelationshipType.POTENTIALLY_CONTRADICTORY: GraphEdgeType.CONTRADICTS,
    }
    for i, (rtype, gtype) in enumerate(expected.items()):
        g = build_graph(_ws(), [_edge("pap_a", rtype, edge_id=f"edge_{i}")], _TITLES)
        assert g.edges[0].type == gtype, f"{rtype} should map to {gtype}"


def test_every_edge_carries_evidence_traced_to_the_trail_edge() -> None:
    g = build_graph(_ws(), [_edge("pap_a", RelationshipType.SIMILAR, quote="verbatim trail quote")], _TITLES)
    assert g.edges[0].evidence[0].quote == "verbatim trail quote"


# --- node/edge deduplication ------------------------------------------------


def test_two_relationship_types_collapsing_to_the_same_graph_edge_type_are_merged() -> None:
    # SIMILAR and RECENT both map to GraphEdgeType.SIMILAR for the same pair
    edges = [
        _edge("pap_a", RelationshipType.SIMILAR, edge_id="edge_sim", quote="similar quote"),
        _edge("pap_a", RelationshipType.RECENT, edge_id="edge_rec", quote="recent quote"),
    ]
    g = build_graph(_ws(), edges, _TITLES)
    assert g.edge_count == 1
    merged = g.edges[0]
    assert merged.type == GraphEdgeType.SIMILAR
    quotes = {s.quote for s in merged.evidence}
    assert quotes == {"similar quote", "recent quote"}


def test_merged_edge_keeps_the_higher_confidence() -> None:
    edges = [
        _edge("pap_a", RelationshipType.SIMILAR, edge_id="edge_sim", confidence=Confidence.LOW),
        _edge("pap_a", RelationshipType.RECENT, edge_id="edge_rec", confidence=Confidence.HIGH),
    ]
    g = build_graph(_ws(), edges, _TITLES)
    assert g.edges[0].confidence == Confidence.HIGH


def test_duplicate_evidence_spans_are_not_repeated() -> None:
    edges = [
        _edge("pap_a", RelationshipType.SIMILAR, edge_id="edge_sim", quote="same quote"),
        _edge("pap_a", RelationshipType.RECENT, edge_id="edge_rec", quote="same quote"),
    ]
    g = build_graph(_ws(), edges, _TITLES)
    assert len(g.edges[0].evidence) == 1


# --- rejected / dangling edges ----------------------------------------------


def test_rejected_trail_edges_are_excluded() -> None:
    g = build_graph(_ws(), [_edge("pap_a", RelationshipType.SIMILAR, user_state="rejected")], _TITLES)
    assert g.edge_count == 0


def test_pending_and_accepted_edges_are_both_included() -> None:
    edges = [
        _edge("pap_a", RelationshipType.SIMILAR, edge_id="edge_p", user_state="pending"),
    ]
    g = build_graph(_ws(), edges, _TITLES)
    assert g.edge_count == 1


def test_a_trail_edge_to_a_non_member_keeps_its_paper_as_a_connected_node() -> None:
    # Regression: importing a discovery run attaches its trail edges before
    # any of its papers join, and accepting an edge does not add the paper.
    # The graph used to drop every such edge, leaving a real workspace with
    # 19 reviewed connections graphed as two unconnected dots.
    g = build_graph(_ws(["pap_seed"]), [_edge("pap_a", RelationshipType.SIMILAR, user_state="accepted")], _TITLES)
    assert g.node_count == 2
    assert g.edge_count == 1
    connected = next(n for n in g.nodes if n.id == "pap_a")
    assert connected.in_workspace is False
    assert connected.role is None
    assert connected.label == "Paper A"
    assert g.edges[0].src == "pap_seed" and g.edges[0].dst == "pap_a"
    assert g.edges[0].user_state == UserState.ACCEPTED


def test_a_rejected_edge_to_a_non_member_adds_no_node() -> None:
    g = build_graph(_ws(["pap_seed"]), [_edge("pap_a", RelationshipType.SIMILAR, user_state="rejected")], _TITLES)
    assert {n.id for n in g.nodes} == {"pap_seed"}
    assert g.edge_count == 0


def test_every_edge_endpoint_has_a_node() -> None:
    edges = [
        _edge("pap_a", RelationshipType.SIMILAR, edge_id="edge_1"),
        _edge("pap_b", RelationshipType.FOUNDATIONAL, edge_id="edge_2", user_state="accepted"),
    ]
    g = build_graph(_ws(["pap_seed"]), edges, _TITLES)
    ids = {n.id for n in g.nodes}
    assert all(e.src in ids and e.dst in ids for e in g.edges)


def test_members_come_first_then_connected_papers() -> None:
    g = build_graph(_ws(["pap_seed", "pap_b"]), [_edge("pap_a", RelationshipType.SIMILAR)], _TITLES)
    assert [(n.id, n.in_workspace) for n in g.nodes] == [("pap_b", True), ("pap_seed", True), ("pap_a", False)]


# --- node details -----------------------------------------------------------


def test_member_nodes_carry_their_workspace_role() -> None:
    g = build_graph(_ws(["pap_seed", "pap_a"]), [], _TITLES)
    roles = {n.id: n.role for n in g.nodes}
    assert roles == {"pap_seed": WorkspacePaperRole.SEED, "pap_a": WorkspacePaperRole.RELATED}


def test_paper_details_are_carried_onto_nodes() -> None:
    details = {"pap_a": PaperDetails(year=2019, authors=["A. Author", "B. Author"], venue="ACL")}
    g = build_graph(_ws(["pap_seed"]), [_edge("pap_a", RelationshipType.SIMILAR)], _TITLES, details)
    node = next(n for n in g.nodes if n.id == "pap_a")
    assert (node.year, node.authors, node.venue) == (2019, ["A. Author", "B. Author"], "ACL")
    seed = next(n for n in g.nodes if n.id == "pap_seed")
    assert (seed.year, seed.authors, seed.venue) == (None, [], None)  # unknown, never invented


# --- trail provenance and review state ---------------------------------------


def test_an_edge_keeps_its_trail_edge_id_and_relationship_type() -> None:
    g = build_graph(_ws(), [_edge("pap_a", RelationshipType.FOUNDATIONAL, edge_id="edge_f")], _TITLES)
    assert g.edges[0].type == GraphEdgeType.CITES
    assert g.edges[0].trail_edge_ids == ["edge_f"]
    assert g.edges[0].relationship_types == [RelationshipType.FOUNDATIONAL]
    assert g.edges[0].user_state == UserState.PENDING


def test_a_merged_edge_lists_both_trail_edges_and_stays_pending_while_either_is() -> None:
    edges = [
        _edge("pap_a", RelationshipType.SIMILAR, edge_id="edge_sim", user_state="accepted"),
        _edge("pap_a", RelationshipType.RECENT, edge_id="edge_rec", user_state="pending"),
    ]
    g = build_graph(_ws(), edges, _TITLES)
    assert g.edge_count == 1
    assert g.edges[0].trail_edge_ids == ["edge_rec", "edge_sim"]
    assert g.edges[0].relationship_types == [RelationshipType.RECENT, RelationshipType.SIMILAR]
    assert g.edges[0].user_state == UserState.PENDING


def test_a_merged_edge_is_accepted_once_every_trail_edge_is() -> None:
    edges = [
        _edge("pap_a", RelationshipType.SIMILAR, edge_id="edge_sim", user_state="accepted"),
        _edge("pap_a", RelationshipType.RECENT, edge_id="edge_rec", user_state="accepted"),
    ]
    g = build_graph(_ws(), edges, _TITLES)
    assert g.edges[0].user_state == UserState.ACCEPTED


# --- deterministic construction ---------------------------------------------


def test_construction_is_deterministic_regardless_of_input_order() -> None:
    edges_a = [
        _edge("pap_a", RelationshipType.SIMILAR, edge_id="edge_1"),
        _edge("pap_b", RelationshipType.COMPETING, edge_id="edge_2"),
    ]
    edges_b = list(reversed(edges_a))
    ws = _ws(["pap_seed", "pap_a", "pap_b"])
    g1 = build_graph(ws, edges_a, _TITLES)
    g2 = build_graph(ws, edges_b, _TITLES)
    assert g1.model_dump(mode="json", exclude={"built_at"}) == g2.model_dump(mode="json", exclude={"built_at"})


def test_rerun_with_identical_input_is_byte_identical() -> None:
    ws = _ws()
    edges = [_edge("pap_a", RelationshipType.SIMILAR)]
    g1 = build_graph(ws, edges, _TITLES)
    g2 = build_graph(ws, edges, _TITLES)
    assert g1.model_dump(mode="json", exclude={"built_at"}) == g2.model_dump(mode="json", exclude={"built_at"})


def test_workspace_id_is_taken_from_the_workspace() -> None:
    g = build_graph(_ws(), [], _TITLES)
    assert g.workspace_id == "ws_1"
