import type {
  Confidence,
  GraphEdgeType,
  RelationshipType,
  ResearchGraph,
  SourceSpan,
} from "@/lib/api/types";

/** Where a paper stands: the seed, a paper collected into the workspace, or
 * a paper reached only through a trail connection that was never added. */
export type NodeKind = "seed" | "member" | "connected";
export type EdgeState = "accepted" | "pending";

export interface GNode {
  id: string;
  title: string;
  kind: NodeKind;
  year: number | null;
  authors: string[];
  venue: string | null;
}

export interface GEdge {
  key: string;
  src: string;
  dst: string;
  type: GraphEdgeType;
  relationshipTypes: RelationshipType[];
  trailEdgeIds: string[];
  state: EdgeState;
  confidence: Confidence;
  evidence: SourceSpan[];
}

export interface GraphModel {
  nodes: GNode[];
  edges: GEdge[];
  byId: Map<string, GNode>;
  /** Every edge touching a node, either direction. */
  incident: Map<string, GEdge[]>;
  seedId: string | null;
}

export interface EdgeStyle {
  /** The trail's own vocabulary, so the graph and the trail read alike. */
  label: string;
  color: string;
  /** SVG stroke-dasharray at zoom 1, or null for a solid line. */
  dash: string | null;
  width: number;
  /** Which end the citation arrow points at ("cites" direction), if any. */
  arrow: "dst" | "src" | null;
  /** How this kind of link reads, as a sentence about the two papers. */
  describe: (src: string, dst: string) => string;
}

// Categorical, not decorative: each relationship keeps one hue across the
// graph, its filter chip and its legend. Citation facts carry arrows in the
// direction of the citation; similarity and tension are undirected.
export const EDGE_STYLE: Record<GraphEdgeType, EdgeStyle> = {
  CITES: { label: "Foundational", color: "#5df0a8", dash: null, width: 1.6, arrow: "dst", describe: (a, b) => `${a} cites ${b}` },
  EXTENDS: { label: "Method extensions", color: "#b8f36b", dash: null, width: 1.9, arrow: "src", describe: (a, b) => `${b} builds on ${a}` },
  SIMILAR: { label: "Similar", color: "#3fd0f0", dash: null, width: 1.4, arrow: null, describe: (a, b) => `${a} and ${b} work on closely matching problems` },
  COMPETES_WITH: { label: "Competing", color: "#e8c15c", dash: "6 5", width: 1.6, arrow: null, describe: (a, b) => `${b} takes a different approach to ${a}'s problem` },
  USES_DATASET: { label: "Shared data", color: "#8fb0ff", dash: "1.5 4.5", width: 1.9, arrow: null, describe: (a, b) => `${a} and ${b} work with the same data` },
  CONTRADICTS: { label: "Possible contradictions", color: "#ff8f8f", dash: "10 4 2 4", width: 1.6, arrow: null, describe: (a, b) => `${b}'s findings may contradict ${a}'s` },
  // Not produced by the backend yet; styled so they would still render legibly.
  USES_METHOD: { label: "Uses a method", color: "#9aa6c4", dash: null, width: 1.4, arrow: "dst", describe: (a, b) => `${a} uses ${b}` },
  SUPPORTS: { label: "Supports", color: "#9aa6c4", dash: null, width: 1.4, arrow: "dst", describe: (a, b) => `${a} supports ${b}` },
  ADDRESSES: { label: "Addresses", color: "#9aa6c4", dash: null, width: 1.4, arrow: "dst", describe: (a, b) => `${a} addresses ${b}` },
  EXPOSES_GAP: { label: "Exposes a gap", color: "#9aa6c4", dash: null, width: 1.4, arrow: "dst", describe: (a, b) => `${a} exposes ${b}` },
};

/** Legend and filter order: citation facts, then similarity, then tension. */
export const EDGE_TYPE_ORDER: GraphEdgeType[] = [
  "CITES",
  "EXTENDS",
  "SIMILAR",
  "USES_DATASET",
  "COMPETES_WITH",
  "CONTRADICTS",
  "USES_METHOD",
  "SUPPORTS",
  "ADDRESSES",
  "EXPOSES_GAP",
];

const RELATIONSHIP_OF: Partial<Record<GraphEdgeType, RelationshipType>> = {
  CITES: "FOUNDATIONAL",
  EXTENDS: "METHOD_EXTENSION",
  SIMILAR: "SIMILAR",
  COMPETES_WITH: "COMPETING",
  USES_DATASET: "DATASET_RELATED",
  CONTRADICTS: "POTENTIALLY_CONTRADICTORY",
};

export const edgeKey = (src: string, dst: string, type: GraphEdgeType) => `${src}|${dst}|${type}`;

/** The graph as the page draws it: paper nodes only (the backend emits no
 * other node types yet), edges between drawn nodes only. Older backends
 * send no membership or review state; every node was a member then, and an
 * edge is treated as accepted -- nothing is invented, only defaulted. */
export function buildModel(graph: ResearchGraph, fallbackSeedId?: string | null): GraphModel {
  const papers = graph.nodes.filter((n) => n.type === "PAPER");
  const seedId = papers.find((n) => n.role === "seed")?.id ?? (papers.some((n) => n.id === fallbackSeedId) ? fallbackSeedId! : null);
  const nodes: GNode[] = papers.map((n) => ({
    id: n.id,
    title: n.label,
    kind: n.id === seedId ? "seed" : n.in_workspace === false ? "connected" : "member",
    year: n.year ?? null,
    authors: n.authors ?? [],
    venue: n.venue ?? null,
  }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges: GEdge[] = graph.edges
    .filter((e) => byId.has(e.src) && byId.has(e.dst) && e.src !== e.dst)
    .map((e) => {
      const fallback = RELATIONSHIP_OF[e.type];
      return {
        key: edgeKey(e.src, e.dst, e.type),
        src: e.src,
        dst: e.dst,
        type: e.type,
        relationshipTypes: e.relationship_types?.length ? e.relationship_types : fallback ? [fallback] : [],
        trailEdgeIds: e.trail_edge_ids ?? [],
        state: e.user_state === "pending" ? "pending" : "accepted",
        confidence: e.confidence,
        evidence: e.evidence,
      };
    });
  const incident = new Map<string, GEdge[]>(nodes.map((n) => [n.id, []]));
  for (const e of edges) {
    incident.get(e.src)!.push(e);
    incident.get(e.dst)!.push(e);
  }
  return { nodes, edges, byId, incident, seedId };
}

export const otherEnd = (e: GEdge, id: string) => (e.src === id ? e.dst : e.src);

/** Everything the layout depends on, and nothing it doesn't: accepting a
 * connection or adding a paper changes how things are drawn, not where. */
export function topologyKey(model: GraphModel): string {
  const nodes = model.nodes.map((n) => `${n.id}@${n.year ?? ""}`).sort();
  const edges = model.edges.map((e) => e.key).sort();
  return `${model.seedId ?? ""}#${nodes.join(",")}#${edges.join(",")}`;
}

export interface GraphFilter {
  hiddenTypes: ReadonlySet<GraphEdgeType>;
  states: ReadonlySet<EdgeState>;
  /** When set, only these nodes (and edges between them) are shown. */
  focus: ReadonlySet<string> | null;
}

export interface Visible {
  nodes: Set<string>;
  edges: Set<string>;
}

/** What the current filters leave on screen. The seed and the workspace's
 * own papers always stay (they are the workspace); a connected paper stays
 * only while at least one of its connections is shown. */
export function visibleParts(model: GraphModel, filter: GraphFilter): Visible {
  const inFocus = (id: string) => !filter.focus || filter.focus.has(id);
  const edges = new Set<string>();
  const nodes = new Set<string>();
  for (const e of model.edges) {
    if (filter.hiddenTypes.has(e.type) || !filter.states.has(e.state)) continue;
    if (!inFocus(e.src) || !inFocus(e.dst)) continue;
    edges.add(e.key);
    nodes.add(e.src);
    nodes.add(e.dst);
  }
  for (const n of model.nodes) {
    if (n.kind !== "connected" && inFocus(n.id)) nodes.add(n.id);
  }
  return { nodes, edges };
}

/** A node plus every node one connection away (any filter ignored: expanding
 * is how hidden neighbours are brought back into view). */
export function neighbourhood(model: GraphModel, id: string): Set<string> {
  const out = new Set([id]);
  for (const e of model.incident.get(id) ?? []) out.add(otherEnd(e, id));
  return out;
}

/** Shortest path between two nodes over the given edges, treating links as
 * undirected (a path is "how these two papers are related", not a
 * citation chain). Returns node ids and edge keys, or null if unconnected. */
export function shortestPath(
  model: GraphModel,
  from: string,
  to: string,
  allowed: ReadonlySet<string>,
): { nodes: string[]; edges: string[] } | null {
  if (!model.byId.has(from) || !model.byId.has(to)) return null;
  if (from === to) return { nodes: [from], edges: [] };
  const prev = new Map<string, { node: string; edge: string }>();
  const seen = new Set([from]);
  const queue = [from];
  while (queue.length > 0) {
    const cur = queue.shift()!;
    // deterministic: neighbours in id order
    const next = (model.incident.get(cur) ?? [])
      .filter((e) => allowed.has(e.key))
      .map((e) => ({ id: otherEnd(e, cur), edge: e.key }))
      .sort((a, b) => a.id.localeCompare(b.id) || a.edge.localeCompare(b.edge));
    for (const { id, edge } of next) {
      if (seen.has(id)) continue;
      seen.add(id);
      prev.set(id, { node: cur, edge });
      if (id === to) {
        const nodes = [to];
        const edges: string[] = [];
        let at = to;
        while (at !== from) {
          const step = prev.get(at)!;
          edges.unshift(step.edge);
          nodes.unshift(step.node);
          at = step.node;
        }
        return { nodes, edges };
      }
      queue.push(id);
    }
  }
  return null;
}

/** Papers matching a search, best first: title prefix, then title words,
 * then authors / venue / year. */
export function searchNodes(model: GraphModel, query: string, limit = 8): GNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored: [number, GNode][] = [];
  for (const n of model.nodes) {
    const title = n.title.toLowerCase();
    let score = -1;
    if (title.startsWith(q)) score = 0;
    else if (title.includes(` ${q}`)) score = 1;
    else if (title.includes(q)) score = 2;
    else if (n.authors.some((a) => a.toLowerCase().includes(q))) score = 3;
    else if ((n.venue ?? "").toLowerCase().includes(q) || String(n.year ?? "") === q) score = 4;
    if (score >= 0) scored.push([score, n]);
  }
  return scored
    .sort((a, b) => a[0] - b[0] || kindRank(a[1]) - kindRank(b[1]) || a[1].title.localeCompare(b[1].title))
    .slice(0, limit)
    .map(([, n]) => n);
}

const kindRank = (n: GNode) => (n.kind === "seed" ? 0 : n.kind === "member" ? 1 : 2);

export function countBy<T extends string>(items: Iterable<T>): Map<T, number> {
  const out = new Map<T, number>();
  for (const it of items) out.set(it, (out.get(it) ?? 0) + 1);
  return out;
}

/** "A. Author", "A. Author and B. Author", or "A. Author et al." */
export function shortAuthors(authors: string[]): string | null {
  if (authors.length === 0) return null;
  if (authors.length === 1) return authors[0];
  if (authors.length === 2) return `${authors[0]} and ${authors[1]}`;
  return `${authors[0]} et al.`;
}
