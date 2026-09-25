import { describe, expect, it } from "vitest";
import { ALPHA_BUCKETS, LINK_DIST, MORPH, NODE_CODES, createField, seededRandom, type Frame } from "./field";

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

  describe("morphing into a research graph", () => {
    const targets = [
      { x: 360, y: 300, r: 17 },
      { x: 820, y: 420, r: 9.5 },
      { x: 600, y: 180, r: 6.5 },
    ];

    function advance(field: ReturnType<typeof createField>, fromMs: number, seconds: number): { frame: Frame; now: number } {
      let now = fromMs;
      let frame = field.step(now, 0, pointer);
      for (let i = 0; i < Math.round(seconds * 60); i++) {
        now += 1000 / 60;
        frame = field.step(now, 1 / 60, pointer);
      }
      return { frame, now };
    }

    const nodesNear = (frame: Frame, x: number, y: number, radius: number) => {
      const [nx, ny, r] = frame.nodes.cols;
      let count = 0;
      for (let i = 0; i < frame.nodes.count; i++) if (r[i] > 0 && Math.hypot(nx[i] - x, ny[i] - y) <= radius) count++;
      return count;
    };

    it("condenses glowing nodes onto each target, with a swarm and a glow around it", () => {
      const field = createField(seededRandom(21));
      field.build(1280, 720);
      let { now } = advance(field, 0, 0.5);
      field.morph(targets);
      ({ now } = advance(field, now, MORPH.converge[1] + 0.05));
      const frame = field.step(now, 0, pointer);
      const [gx, gy] = frame.glows.cols;
      for (const t of targets) {
        expect(nodesNear(frame, t.x, t.y, 3)).toBeGreaterThanOrEqual(1); // the anchor sits on the target
        expect(nodesNear(frame, t.x, t.y, t.r + 26)).toBeGreaterThanOrEqual(4); // recruits ring it
        let glowing = false;
        for (let i = 0; i < frame.glows.count; i++) if (Math.hypot(gx[i] - t.x, gy[i] - t.y) < 4) glowing = true;
        expect(glowing).toBe(true);
      }
    });

    it("quiets the rest of the field while the graph is shown, and gives it back on release", () => {
      const field = createField(seededRandom(22));
      field.build(1280, 720);
      let { frame, now } = advance(field, 0, 1);
      const normal = frame.links.count;
      field.morph(targets);
      ({ frame, now } = advance(field, now, MORPH.handoff[1] + 0.5));
      const calm = frame.links.count;
      expect(calm).toBeLessThan(normal * 0.8);
      // the knots have dissolved: nothing is left parked on a target
      for (const t of targets) expect(nodesNear(frame, t.x, t.y, 2)).toBe(0);
      field.release();
      ({ frame } = advance(field, now, MORPH.release + MORPH.recover + 0.3));
      expect(frame.links.count).toBeGreaterThan(normal * 0.85);
    });

    it("jumps straight to the calm level for a still frame", () => {
      const field = createField(seededRandom(23));
      field.build(1280, 720);
      const normal = field.step(0, 0, pointer).links.count;
      field.calmNow(true);
      const calm = field.step(0, 0, pointer).links.count;
      expect(calm).toBeLessThan(normal * 0.8);
      field.calmNow(false);
      expect(field.step(0, 0, pointer).links.count).toBe(normal);
    });
  });

  it("uses a lighter field on narrow screens", () => {
    const phone = run(1, 390, 844, 0);
    const desktop = run(1, 1920, 1080, 0);
    expect(phone.nodes.count).toBeLessThan(desktop.nodes.count);
  });
});
