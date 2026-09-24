import { GLOW_STOPS } from "./field";

export type AnyCanvas = HTMLCanvasElement | OffscreenCanvas;

export const GLOW_SPRITE_SIZE = 64;

/** The soft radial glow drawn for halos, flashing nodes and pulse heads.
 * An OffscreenCanvas where available (always, inside a worker), else a
 * detached page canvas. Both renderers draw this same bitmap. */
export function makeGlowSprite(): AnyCanvas | null {
  const size = GLOW_SPRITE_SIZE;
  const sprite: AnyCanvas =
    typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(size, size) : Object.assign(document.createElement("canvas"), { width: size, height: size });
  const g = sprite.getContext("2d") as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null;
  if (!g) return null;
  const half = size / 2;
  const grad = g.createRadialGradient(half, half, 0, half, half, half);
  for (const [offset, [r, gr, b, a]] of GLOW_STOPS) grad.addColorStop(offset, `rgba(${r}, ${gr}, ${b}, ${a})`);
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  return sprite;
}
