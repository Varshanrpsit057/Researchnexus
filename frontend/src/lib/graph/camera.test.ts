import { describe, expect, it } from "vitest";
import { fitCamera, lerpAbout, nodeZoom, prominentFit, toScreen, type Insets } from "./camera";

const insets: Insets = { top: 76, right: 56, bottom: 72, left: 88 };
const room: Insets = { top: 44, right: 40, bottom: 48, left: 68 };

function inside(cam: ReturnType<typeof fitCamera>, b: { minX: number; maxX: number; minY: number; maxY: number }, w: number, h: number, r: Insets) {
  const lo = toScreen(cam, { x: b.minX, y: b.minY });
  const hi = toScreen(cam, { x: b.maxX, y: b.maxY });
  return lo.x >= r.left - 1e-6 && lo.y >= r.top - 1e-6 && hi.x <= w - r.right + 1e-6 && hi.y <= h - r.bottom + 1e-6;
}

describe("prominentFit", () => {
  it("draws a small graph a fifth larger than the plain fit, centred where the fit put it", () => {
    const b = { minX: -100, maxX: 100, minY: -60, maxY: 60 };
    const base = fitCamera(b, 1280, 700, insets);
    const cam = prominentFit(b, 1280, 700, insets, room);
    expect(cam.k / base.k).toBeCloseTo(1.2, 6);
    expect(toScreen(cam, { x: 0, y: 0 })).toEqual(toScreen(base, { x: 0, y: 0 }));
  });

  it("grows a large graph only as far as the stage still holds all of it", () => {
    const b = { minX: -600, maxX: 600, minY: -300, maxY: 300 };
    const base = fitCamera(b, 1280, 700, insets);
    const cam = prominentFit(b, 1280, 700, insets, room);
    expect(cam.k).toBeGreaterThan(base.k);
    expect(cam.k / base.k).toBeLessThan(1.2);
    expect(inside(cam, b, 1280, 700, room)).toBe(true);
  });

  it("never shrinks the plain fit", () => {
    const b = { minX: -2000, maxX: 2000, minY: -2000, maxY: 2000 };
    expect(prominentFit(b, 400, 700, insets, { top: 400, right: 0, bottom: 400, left: 0 }).k).toBeCloseTo(fitCamera(b, 400, 700, insets).k, 9);
  });
});

describe("lerpAbout", () => {
  it("moves the anchor point in a straight line while the scale changes", () => {
    const a = { x: 100, y: 50, k: 1 };
    const b = { x: 40, y: 20, k: 1.2 };
    const p = { x: 300, y: 200 };
    expect(lerpAbout(a, b, p, 0)).toEqual(a);
    const end = lerpAbout(a, b, p, 1);
    expect(end.k).toBeCloseTo(1.2, 9);
    expect(end.x).toBeCloseTo(40, 9);
    expect(end.y).toBeCloseTo(20, 9);
    const mid = toScreen(lerpAbout(a, b, p, 0.5), p);
    const sa = toScreen(a, p);
    const sb = toScreen(b, p);
    expect(mid.x).toBeCloseTo((sa.x + sb.x) / 2, 9);
    expect(mid.y).toBeCloseTo((sa.y + sb.y) / 2, 9);
  });
});

describe("nodeZoom", () => {
  it("lets nodes grow with a prominent zoom, within bounds", () => {
    expect(nodeZoom(1.62)).toBeCloseTo(1.6, 9);
    expect(nodeZoom(1.35)).toBeCloseTo(1.35, 9);
    expect(nodeZoom(0.2)).toBe(0.75);
  });
});
