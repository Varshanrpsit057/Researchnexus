import type { Bounds, Point } from "./layout";

/** screen = graph * k + (x, y) */
export interface Camera {
  x: number;
  y: number;
  k: number;
}

export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 3.2;

const clampZoom = (k: number) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, k));

export const toScreen = (cam: Camera, p: Point): Point => ({ x: p.x * cam.k + cam.x, y: p.y * cam.k + cam.y });
export const toGraph = (cam: Camera, p: Point): Point => ({ x: (p.x - cam.x) / cam.k, y: (p.y - cam.y) / cam.k });

/** The whole of `bounds` inside the viewport minus `insets`, never zoomed in
 * past `maxK` (a two-paper graph should not fill the screen with two dots). */
export function fitCamera(bounds: Bounds, width: number, height: number, insets: Insets, maxK = 1.35): Camera {
  const availW = Math.max(1, width - insets.left - insets.right);
  const availH = Math.max(1, height - insets.top - insets.bottom);
  const bw = Math.max(1, bounds.maxX - bounds.minX);
  const bh = Math.max(1, bounds.maxY - bounds.minY);
  const k = clampZoom(Math.min(availW / bw, availH / bh, maxK));
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;
  return { k, x: insets.left + availW / 2 - cx * k, y: insets.top + availH / 2 - cy * k };
}

/** Zoom by `factor`, keeping the graph point under screen point (sx, sy) fixed. */
export function zoomAt(cam: Camera, factor: number, sx: number, sy: number): Camera {
  const k = clampZoom(cam.k * factor);
  const g = toGraph(cam, { x: sx, y: sy });
  return { k, x: sx - g.x * k, y: sy - g.y * k };
}

/** Put graph point `p` at the centre of the viewport minus `insets`. */
export function centerOn(cam: Camera, p: Point, width: number, height: number, insets: Insets, k = cam.k): Camera {
  const cx = insets.left + (width - insets.left - insets.right) / 2;
  const cy = insets.top + (height - insets.top - insets.bottom) / 2;
  return { k, x: cx - p.x * k, y: cy - p.y * k };
}

export function boundsOf(points: Point[], pad = 0): Bounds {
  const b: Bounds = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
  for (const p of points) {
    b.minX = Math.min(b.minX, p.x - pad);
    b.maxX = Math.max(b.maxX, p.x + pad);
    b.minY = Math.min(b.minY, p.y - pad);
    b.maxY = Math.max(b.maxY, p.y + pad);
  }
  if (points.length === 0) return { minX: -pad, maxX: pad, minY: -pad, maxY: pad };
  return b;
}

export const lerpCamera = (a: Camera, b: Camera, t: number): Camera => ({
  x: a.x + (b.x - a.x) * t,
  y: a.y + (b.y - a.y) * t,
  k: a.k * Math.pow(b.k / a.k, t),
});
