import { describe, expect, it } from "vitest";
import type { GraphNode, ResearchGraph } from "@/lib/api/types";
import { fitCamera, toScreen, zoomAt, centerOn, lerpCamera } from "./camera";
import { placeLabels, truncate } from "./labels";
import { layoutGraph } from "./layout";
import { buildModel } from "./model";

function paper(id: string, year: number | null, extra: Partial<GraphNode> = {}): GraphNode {
  return { id, type: "PAPER", label: id, paper_ids: [id], span: null, in_workspace: false, role: null, year, authors: [], venue: null, ...extra };
}

function star(years: (number | null)[], seedYear: number | null = 2020): ResearchGraph {
  const leaves = years.map((y, i) => paper(`p${i}`, y));
  return {
    workspace_id: "ws",
    nodes: [paper("seed", seedYear, { role: "seed", in_workspace: true }), ...leaves],
    edges: leaves.map((l, i) => ({
      src: "seed",
      dst: l.id,
      type: i % 3 === 0 ? "CITES" : i % 3 === 1 ? "SIMILAR" : "COMPETES_WITH",
      evidence: [],
      confidence: "medium",
      user_state: "pending",
    })),
    built_at: "",
    node_count: leaves.length + 1,
    edge_count: leaves.length,
  };
}

describe("graph layout", () => {
  const years = [2013, 2015, 2016, 2017, 2018, 2018, 2018, 2018, 2019, 2021, 2022, 2023];

  it("is deterministic", () => {
    const a = layoutGraph(buildModel(star(years)));
    const b = layoutGraph(buildModel(star(years)));
    expect([...a.pos]).toEqual([...b.pos]);
  });

  it("puts time on the x axis: older work left of the seed, newer right, seed at the origin", () => {
    const m = buildModel(star(years));
    const { pos, timeline } = layoutGraph(m);
    expect(pos.get("seed")).toEqual({ x: 0, y: 0 });
    expect(timeline).not.toBeNull();
    expect(timeline!.seedYear).toBe(2020);
    for (const n of m.nodes) {
      if (n.id === "seed" || n.year == null) continue;
      if (n.year < 2020) expect(pos.get(n.id)!.x).toBeLessThan(0);
      if (n.year > 2020) expect(pos.get(n.id)!.x).toBeGreaterThan(0);
    }
    // same-year papers share a column instead of piling up
    const col2018 = m.nodes.filter((n) => n.year === 2018).map((n) => pos.get(n.id)!);
    const xs = col2018.map((p) => p.x);
    expect(Math.max(...xs) - Math.min(...xs)).toBeLessThan(80);
    expect(timeline!.ticks[0]).toBe(2013);
  });

  it("keeps every pair of papers apart", () => {
    const { pos } = layoutGraph(buildModel(star(years)));
    const pts = [...pos.values()];
    for (let i = 0; i < pts.length; i++)
      for (let j = i + 1; j < pts.length; j++) expect(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y)).toBeGreaterThan(40);
  });

  it("lays out undated graphs without a time axis", () => {
    const { pos, timeline } = layoutGraph(buildModel(star([null, null, null], null)));
    expect(timeline).toBeNull();
    expect(pos.size).toBe(4);
    for (const p of pos.values()) expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
  });

  it("settles a changed graph from where it was", () => {
    // one mid-range paper rejected: the year range (and so the axis) is unchanged
    const full = star(years);
    const first = layoutGraph(buildModel(full));
    const fewer = { ...full, nodes: full.nodes.filter((n) => n.id !== "p5"), edges: full.edges.filter((e) => e.dst !== "p5") };
    const settled = layoutGraph(buildModel(fewer), first.pos);
    expect(settled.pos.has("p5")).toBe(false);
    for (const [id, p] of settled.pos) {
      const before = first.pos.get(id)!;
      expect(Math.hypot(p.x - before.x, p.y - before.y)).toBeLessThan(60);
    }
  });
});

describe("graph camera", () => {
  const bounds = { minX: -300, maxX: 500, minY: -120, maxY: 200 };
  const insets = { top: 40, right: 400, bottom: 60, left: 40 };

  it("fits the bounds inside the clear area", () => {
    const cam = fitCamera(bounds, 1200, 700, insets);
    const tl = toScreen(cam, { x: bounds.minX, y: bounds.minY });
    const br = toScreen(cam, { x: bounds.maxX, y: bounds.maxY });
    expect(tl.x).toBeGreaterThanOrEqual(insets.left - 0.01);
    expect(tl.y).toBeGreaterThanOrEqual(insets.top - 0.01);
    expect(br.x).toBeLessThanOrEqual(1200 - insets.right + 0.01);
    expect(br.y).toBeLessThanOrEqual(700 - insets.bottom + 0.01);
  });

  it("never blows a tiny graph up past the cap", () => {
    expect(fitCamera({ minX: 0, maxX: 10, minY: 0, maxY: 10 }, 1200, 700, insets).k).toBe(1.35);
  });

  it("zooms about the pointer and clamps the zoom", () => {
    const cam = { x: 100, y: 50, k: 1 };
    const z = zoomAt(cam, 2, 400, 300);
    const g = { x: (400 - cam.x) / cam.k, y: (300 - cam.y) / cam.k };
    expect(toScreen(z, g).x).toBeCloseTo(400);
    expect(toScreen(z, g).y).toBeCloseTo(300);
    expect(zoomAt(cam, 100, 0, 0).k).toBe(3.2);
    expect(zoomAt(cam, 0.001, 0, 0).k).toBe(0.2);
  });

  it("centres a point in the clear area and interpolates smoothly", () => {
    const c = centerOn({ x: 0, y: 0, k: 1 }, { x: 50, y: 50 }, 1200, 700, insets);
    expect(toScreen(c, { x: 50, y: 50 })).toEqual({ x: 40 + 760 / 2, y: 40 + 600 / 2 });
    const mid = lerpCamera({ x: 0, y: 0, k: 1 }, { x: 100, y: 100, k: 4 }, 0.5);
    expect(mid).toEqual({ x: 50, y: 50, k: 2 });
  });
});

describe("graph labels", () => {
  it("truncates at a word boundary", () => {
    expect(truncate("Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", 30)).toBe("Retrieval-Augmented…");
    expect(truncate("Short", 30)).toBe("Short");
  });

  it("keeps labels on screen: a node at the right edge is labelled on its left", () => {
    const [label] = placeLabels(
      [{ id: "edge", x: 790, y: 300, r: 8, text: "LinkBERT: Pretraining Language Models with Document Links", priority: 1, maxChars: 30 }],
      [{ x: 790, y: 300, r: 8 }],
      { width: 800, height: 600 },
    );
    expect(label.anchor).toBe("end");
    expect(label.x).toBeLessThan(790);
  });

  it("shortens a title that fits nowhere at full length instead of dropping it", () => {
    const [label] = placeLabels(
      [{ id: "seed", x: 200, y: 300, r: 17, text: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", priority: 1, maxChars: 46 }],
      [{ x: 200, y: 300, r: 17 }],
      { width: 390, height: 600 },
    );
    expect(label).toBeDefined();
    expect(label.truncated).toBe(true);
  });

  it("places higher priority labels first and never overlaps two labels", () => {
    const nodes = [
      { x: 100, y: 100, r: 8 },
      { x: 104, y: 104, r: 8 },
    ];
    const placed = placeLabels(
      [
        { id: "low", x: 104, y: 104, r: 8, text: "Low priority paper", priority: 1, maxChars: 30 },
        { id: "high", x: 100, y: 100, r: 8, text: "High priority paper", priority: 9, maxChars: 30 },
      ],
      nodes,
      { width: 800, height: 600 },
    );
    expect(placed[0].id).toBe("high");
    const boxes = placed.map((l) => ({ l, w: l.text.length * 6.7 }));
    if (placed.length === 2) {
      const [a, b] = boxes;
      const ax0 = a.l.anchor === "start" ? a.l.x : a.l.anchor === "end" ? a.l.x - a.w : a.l.x - a.w / 2;
      const bx0 = b.l.anchor === "start" ? b.l.x : b.l.anchor === "end" ? b.l.x - b.w : b.l.x - b.w / 2;
      const overlapX = ax0 < bx0 + b.w && bx0 < ax0 + a.w;
      const overlapY = Math.abs(a.l.y - b.l.y) < 16;
      expect(overlapX && overlapY).toBe(false);
    }
  });
});
