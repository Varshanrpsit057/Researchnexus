import type { GraphEdgeType } from "@/lib/api/types";
import type { GraphModel, NodeKind } from "./model";

export interface Point {
  x: number;
  y: number;
}

export interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export interface Timeline {
  /** Year -> x in graph space. */
  yearX: (year: number) => number;
  ticks: number[];
  seedYear: number | null;
}

export interface Layout {
  pos: Map<string, Point>;
  bounds: Bounds;
  /** Present when at least two distinct publication years are known. */
  timeline: Timeline | null;
}

/** Drawn radius per kind, in graph units (screen px at zoom 1). */
export const NODE_RADIUS: Record<NodeKind, number> = { seed: 17, member: 9.5, connected: 6.5 };

// Spacing is the same for every kind, so accepting a connection or adding a
// paper (which changes how a node is drawn) never moves anything.
const SPACING = 26;
const LINK_LENGTH = 170;

// Vertical tendency per relationship: similarity above the seed's line,
// citation facts along it, shared data and tension below it.
const LANE: Partial<Record<GraphEdgeType, number>> = {
  SIMILAR: -1,
  CITES: 0,
  EXTENDS: 0,
  USES_DATASET: 0.7,
  COMPETES_WITH: 1.1,
  CONTRADICTS: 1.2,
};

function hash(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Deterministic unit value per node id (and a salt), in [0, 1). */
const unit = (id: string, salt: number) => (hash(`${salt}:${id}`) % 100_000) / 100_000;

function niceStep(span: number): number {
  if (span <= 12) return 1;
  if (span <= 30) return 5;
  if (span <= 80) return 10;
  return 20;
}

/** Positions for every node, meaningful rather than decorative: x is
 * publication year (older work to the left of the seed, newer to the right)
 * whenever years are known, y separates papers by how they relate to the
 * seed, and a short force pass keeps everything legible. Deterministic for a
 * given graph; pass the previous positions to settle a changed graph from
 * where it was instead of from scratch. */
export function layoutGraph(model: GraphModel, prev?: ReadonlyMap<string, Point>): Layout {
  const nodes = [...model.nodes].sort((a, b) => a.id.localeCompare(b.id));
  const n = nodes.length;
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const seedIdx = model.seedId != null ? (index.get(model.seedId) ?? -1) : -1;

  const years = nodes.map((node) => node.year).filter((y): y is number => y != null);
  const distinct = new Set(years);
  let timeline: Timeline | null = null;
  const xTarget = new Array<number | null>(n).fill(null);
  if (distinct.size >= 2) {
    const minYear = Math.min(...years);
    const maxYear = Math.max(...years);
    const sorted = [...years].sort((a, b) => a - b);
    const seedYear = seedIdx >= 0 ? nodes[seedIdx].year : null;
    const ref = seedYear ?? sorted[sorted.length >> 1];
    const perYear = Math.max(46, Math.min(150, 900 / Math.max(1, maxYear - minYear)));
    const yearX = (year: number) => (year - ref) * perYear;
    const step = niceStep(maxYear - minYear);
    // round years on the step, plus the seed's year and the range's ends
    const tickSet = new Set([minYear, maxYear]);
    if (seedYear != null) tickSet.add(seedYear);
    for (let y = Math.ceil(minYear / step) * step; y <= maxYear; y += step) tickSet.add(y);
    const ticks = [...tickSet].sort((a, b) => a - b);
    timeline = { yearX, ticks, seedYear };
    nodes.forEach((node, i) => {
      if (node.year != null) xTarget[i] = yearX(node.year);
    });
  }

  const lane = new Array<number>(n).fill(0);
  const edgePairs: [number, number][] = [];
  for (const e of model.edges) {
    const a = index.get(e.src);
    const b = index.get(e.dst);
    if (a == null || b == null) continue;
    edgePairs.push([a, b]);
    const l = LANE[e.type] ?? 0;
    // a node takes the lane of its most "tense" relationship
    for (const i of [a, b]) if (i !== seedIdx && Math.abs(l) > Math.abs(lane[i])) lane[i] = l;
  }

  const x = new Float64Array(n);
  const y = new Float64Array(n);
  const seedX = seedIdx >= 0 ? (xTarget[seedIdx] ?? 0) : 0;
  nodes.forEach((node, i) => {
    const before = prev?.get(node.id);
    if (before) {
      x[i] = before.x;
      y[i] = before.y;
    } else {
      x[i] = xTarget[i] ?? (unit(node.id, 1) - 0.5) * 260;
      y[i] = lane[i] * 150 + (unit(node.id, 2) - 0.5) * 260;
    }
  });
  if (seedIdx >= 0) {
    x[seedIdx] = seedX;
    y[seedIdx] = 0;
  }

  const warm = prev != null && nodes.every((node) => prev.has(node.id));
  const iterations = warm ? 90 : n > 150 ? 160 : 320;
  const startAlpha = warm ? 0.35 : 1;
  const fx = new Float64Array(n);
  const fy = new Float64Array(n);
  for (let it = 0; it < iterations; it++) {
    const alpha = startAlpha * (1 - it / iterations);
    fx.fill(0);
    fy.fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = x[i] - x[j];
        let dy = y[i] - y[j];
        let d2 = dx * dx + dy * dy;
        if (d2 < 1e-6) {
          // coincident: split them along a stable direction
          dx = unit(nodes[i].id, 3) - 0.5;
          dy = unit(nodes[j].id, 4) - 0.5;
          d2 = dx * dx + dy * dy || 1;
        }
        const d = Math.sqrt(d2);
        const f = Math.min(40, (6400 * alpha) / d2);
        const ux = dx / d;
        const uy = dy / d;
        // x is mostly owned by the year axis when there is one
        const kx = timeline ? 0.35 : 1;
        fx[i] += ux * f * kx;
        fy[i] += uy * f;
        fx[j] -= ux * f * kx;
        fy[j] -= uy * f;
      }
    }
    for (const [a, b] of edgePairs) {
      const dx = x[b] - x[a];
      const dy = y[b] - y[a];
      const d = Math.max(1, Math.hypot(dx, dy));
      const pull = (d - LINK_LENGTH) * 0.04 * alpha;
      fx[a] += (dx / d) * pull;
      fy[a] += (dy / d) * pull;
      fx[b] -= (dx / d) * pull;
      fy[b] -= (dy / d) * pull;
    }
    for (let i = 0; i < n; i++) {
      if (i === seedIdx) continue;
      const xt = xTarget[i];
      x[i] += Math.max(-24, Math.min(24, fx[i]));
      y[i] += Math.max(-24, Math.min(24, fy[i]));
      x[i] += ((xt ?? seedX) - x[i]) * (xt != null ? 0.2 : 0.01);
      y[i] += (lane[i] * 150 - y[i]) * 0.012 * alpha;
    }
    // collisions: nothing closer than two spacing radii
    const min = SPACING * 2;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = x[j] - x[i];
        const dy = y[j] - y[i];
        const d = Math.hypot(dx, dy);
        if (d >= min || d === 0) continue;
        const push = (min - d) / d;
        if (i === seedIdx) {
          x[j] += dx * push;
          y[j] += dy * push;
        } else if (j === seedIdx) {
          x[i] -= dx * push;
          y[i] -= dy * push;
        } else {
          x[i] -= dx * push * 0.5;
          y[i] -= dy * push * 0.5;
          x[j] += dx * push * 0.5;
          y[j] += dy * push * 0.5;
        }
      }
    }
  }

  const pos = new Map<string, Point>();
  const bounds: Bounds = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
  nodes.forEach((node, i) => {
    const p = { x: Math.round(x[i] * 10) / 10, y: Math.round(y[i] * 10) / 10 };
    pos.set(node.id, p);
    bounds.minX = Math.min(bounds.minX, p.x);
    bounds.maxX = Math.max(bounds.maxX, p.x);
    bounds.minY = Math.min(bounds.minY, p.y);
    bounds.maxY = Math.max(bounds.maxY, p.y);
  });
  if (n === 0) Object.assign(bounds, { minX: 0, maxX: 0, minY: 0, maxY: 0 });
  return { pos, bounds, timeline };
}
