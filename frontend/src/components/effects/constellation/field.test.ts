import { describe, expect, it } from "vitest";
import { ALPHA_BUCKETS, LINK_DIST, NODE_CODES, createField, seededRandom, type Frame } from "./field";

const pointer = { x: 0.5, y: 0.4 };

function run(seed: number, width: number, height: number, steps: number): Frame {
  const field = createField(seededRandom(seed));
  field.build(width, height);
  let frame = field.step(0, 0, pointer);
  for (let i = 1; i <= steps; i++) frame = field.step(i * 16.7, 1 / 60, pointer);
  return frame;
}

function snapshot(frame: Frame) {
  const cols = (items: Frame["links"]) => items.cols.map((c) => Array.from(c.subarray(0, items.count)));
  return { links: cols(frame.links), nodes: cols(frame.nodes), halos: cols(frame.halos) };
}

describe("constellation field", () => {
  it("is reproducible for a given seed", () => {
    expect(snapshot(run(7, 1366, 768, 30))).toEqual(snapshot(run(7, 1366, 768, 30)));
    expect(snapshot(run(7, 1366, 768, 30))).not.toEqual(snapshot(run(8, 1366, 768, 30)));
  });

  it("only links nodes within their class's distance, with a valid style code", () => {
    const frame = run(3, 1440, 900, 120);
    const [ax, ay, bx, by, , , code, curved] = frame.links.cols;
    expect(frame.links.count).toBeGreaterThan(1000);
    for (let e = 0; e < frame.links.count; e++) {
      const d = Math.hypot(bx[e] - ax[e], by[e] - ay[e]);
      const cls = curved[e] ? 1 : 0;
      expect(d).toBeLessThan(LINK_DIST[cls]);
      expect(Math.floor(code[e] / ALPHA_BUCKETS)).toBe(cls);
    }
  });

  it("keeps every drawn node on screen with a valid style code", () => {
    const frame = run(5, 390, 844, 60);
    const [x, y, r, code] = frame.nodes.cols;
    expect(frame.nodes.count).toBeGreaterThan(100);
    for (let i = 0; i < frame.nodes.count; i++) {
      expect(x[i]).toBeGreaterThanOrEqual(-6);
      expect(x[i]).toBeLessThanOrEqual(390 + 6);
      expect(y[i]).toBeGreaterThanOrEqual(-6);
      expect(y[i]).toBeLessThanOrEqual(844 + 6);
      expect(r[i]).toBeGreaterThan(0);
      expect(code[i]).toBeGreaterThanOrEqual(0);
      expect(code[i]).toBeLessThan(NODE_CODES);
    }
  });

  it("holds still when stepped with no elapsed time", () => {
    const field = createField(seededRandom(11));
    field.build(800, 600);
    const first = Array.from(field.step(1000, 0, pointer).nodes.cols[0].subarray(0, 50));
    const second = Array.from(field.step(5000, 0, pointer).nodes.cols[0].subarray(0, 50));
    expect(second).toEqual(first);
  });

  it("uses a lighter field on narrow screens", () => {
    const phone = run(1, 390, 844, 0);
    const desktop = run(1, 1920, 1080, 0);
    expect(phone.nodes.count).toBeLessThan(desktop.nodes.count);
  });
});
