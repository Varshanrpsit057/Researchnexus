import { describe, expect, it } from "vitest";
import type { GraphEdgeRecord, GraphNode, ResearchGraph } from "@/lib/api/types";
import { buildModel, edgeKey, neighbourhood, searchNodes, shortestPath, topologyKey, visibleParts, type EdgeState } from "./model";

function node(id: string, extra: Partial<GraphNode> = {}): GraphNode {
  return { id, type: "PAPER", label: `Paper ${id}`, paper_ids: [id], span: null, in_workspace: true, role: "related", year: 2020, authors: [], venue: null, ...extra };
}

function edge(src: string, dst: string, extra: Partial<GraphEdgeRecord> = {}): GraphEdgeRecord {
  return {
    src,
    dst,
    type: "SIMILAR",
    evidence: [],
    confidence: "medium",
    trail_edge_ids: [`e_${dst}`],
    relationship_types: ["SIMILAR"],
    user_state: "accepted",
    ...extra,
  };
}

function graph(nodes: GraphNode[], edges: GraphEdgeRecord[]): ResearchGraph {
  return { workspace_id: "ws_1", nodes, edges, built_at: "2026-09-25T00:00:00Z", node_count: nodes.length, edge_count: edges.length };
}

// seed -> a (member, accepted), seed -> b (connected, pending, cites), seed -> c (connected, competes)
const G = graph(
  [
    node("seed", { role: "seed", year: 2020, label: "Retrieval-Augmented Generation" }),
    node("a", { year: 2021, label: "Dense Passage Retrieval", authors: ["V. Karpukhin"] }),
    node("b", { in_workspace: false, role: null, year: 2017, label: "Reading Wikipedia to Answer Open-Domain Questions" }),
    node("c", { in_workspace: false, role: null, year: 2022, label: "A Symbolic Rival" }),
  ],
  [
    edge("seed", "a"),
    edge("seed", "b", { type: "CITES", relationship_types: ["FOUNDATIONAL"], user_state: "pending" }),
    edge("seed", "c", { type: "COMPETES_WITH", relationship_types: ["COMPETING"], user_state: "pending" }),
  ],
);

const ALL: Set<EdgeState> = new Set(["accepted", "pending"]);

describe("graph model", () => {
  it("reads each paper's standing from the graph: seed, member, or connected", () => {
    const m = buildModel(G);
    expect(m.seedId).toBe("seed");
    expect(Object.fromEntries(m.nodes.map((n) => [n.id, n.kind]))).toEqual({ seed: "seed", a: "member", b: "connected", c: "connected" });
    expect(m.edges.find((e) => e.dst === "b")).toMatchObject({ state: "pending", relationshipTypes: ["FOUNDATIONAL"], trailEdgeIds: ["e_b"] });
    expect(m.incident.get("seed")).toHaveLength(3);
  });

  it("falls back sensibly for an older backend: members everywhere, accepted edges, the workspace's seed id", () => {
    const old = graph(
      [
        { id: "s", type: "PAPER", label: "S", paper_ids: ["s"], span: null },
        { id: "t", type: "PAPER", label: "T", paper_ids: ["t"], span: null },
      ],
      [{ src: "s", dst: "t", type: "EXTENDS", evidence: [], confidence: "low" }],
    );
    const m = buildModel(old, "s");
    expect(m.seedId).toBe("s");
    expect(m.byId.get("t")!.kind).toBe("member");
    expect(m.edges[0]).toMatchObject({ state: "accepted", relationshipTypes: ["METHOD_EXTENSION"], trailEdgeIds: [] });
  });

  it("drops edges whose endpoints are not drawn", () => {
    const m = buildModel(graph([node("seed", { role: "seed" })], [edge("seed", "ghost")]));
    expect(m.edges).toHaveLength(0);
  });

  it("filters by relationship and review state, keeping workspace papers but not orphaned connected ones", () => {
    const m = buildModel(G);
    const onlyAccepted = visibleParts(m, { hiddenTypes: new Set(), states: new Set(["accepted"]), focus: null });
    expect([...onlyAccepted.nodes].sort()).toEqual(["a", "seed"]);
    expect([...onlyAccepted.edges]).toEqual([edgeKey("seed", "a", "SIMILAR")]);

    const noSimilar = visibleParts(m, { hiddenTypes: new Set(["SIMILAR"]), states: ALL, focus: null });
    expect(noSimilar.nodes.has("a")).toBe(true); // a member stays, just unlinked
    expect(noSimilar.edges.has(edgeKey("seed", "a", "SIMILAR"))).toBe(false);
  });

  it("focuses on a paper's neighbourhood", () => {
    const m = buildModel(G);
    const focus = neighbourhood(m, "b");
    expect([...focus].sort()).toEqual(["b", "seed"]);
    const v = visibleParts(m, { hiddenTypes: new Set(), states: ALL, focus });
    expect([...v.nodes].sort()).toEqual(["b", "seed"]);
    expect(v.edges.size).toBe(1);
  });

  it("traces the shortest path between two papers over the shown edges", () => {
    const m = buildModel(G);
    const all = new Set(m.edges.map((e) => e.key));
    expect(shortestPath(m, "b", "c", all)).toEqual({
      nodes: ["b", "seed", "c"],
      edges: [edgeKey("seed", "b", "CITES"), edgeKey("seed", "c", "COMPETES_WITH")],
    });
    const withoutC = new Set([...all].filter((k) => !k.includes("COMPETES")));
    expect(shortestPath(m, "b", "c", withoutC)).toBeNull();
    expect(shortestPath(m, "a", "a", all)).toEqual({ nodes: ["a"], edges: [] });
  });

  it("searches titles first, then authors and years", () => {
    const m = buildModel(G);
    expect(searchNodes(m, "dense").map((n) => n.id)).toEqual(["a"]);
    expect(searchNodes(m, "retrieval").map((n) => n.id)).toEqual(["seed", "a"]);
    expect(searchNodes(m, "karpukhin").map((n) => n.id)).toEqual(["a"]);
    expect(searchNodes(m, "2017").map((n) => n.id)).toEqual(["b"]);
    expect(searchNodes(m, "   ")).toEqual([]);
  });

  it("keys the layout on topology only: review decisions and additions don't move anything", () => {
    const before = topologyKey(buildModel(G));
    const decided = graph(
      G.nodes.map((n) => (n.id === "b" ? { ...n, in_workspace: true, role: "related" as const } : n)),
      G.edges.map((e) => ({ ...e, user_state: "accepted" as const })),
    );
    expect(topologyKey(buildModel(decided))).toBe(before);
    const rejected = graph(G.nodes.filter((n) => n.id !== "c"), G.edges.filter((e) => e.dst !== "c"));
    expect(topologyKey(buildModel(rejected))).not.toBe(before);
  });
});
