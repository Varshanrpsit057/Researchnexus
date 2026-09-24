/* Canvas 2D renderer -- the fallback when WebGL2 is unavailable, drawing a
 * `Frame` exactly as the original single-file component did. Works on a
 * page canvas or an OffscreenCanvas inside a worker.
 *
 * Links are counting-sorted into their style codes and drawn with one reused
 * context path per code (no per-frame Path2D allocations, so no GC stutter);
 * mesh links stay at or under one device pixel wide so the GPU can take its
 * cheap hairline path; tiny nodes are rects rather than arcs; glow sprites
 * are only drawn for the few nodes currently flashing. */

import {
  HALO_ALPHA,
  LINK_CODES,
  LINK_COLORS,
  LINK_WIDTH_DEVICE_PX,
  NODE_BUCKETS,
  NODE_CODES,
  NODE_COLORS,
  TAU,
  TRAIL_COLOR,
  rgbaCss,
  type Frame,
} from "./field";
import { makeGlowSprite, type AnyCanvas } from "./sprite";

type Ctx2D = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

const LINK_STYLES = LINK_COLORS.map(rgbaCss);
const NODE_STYLES = NODE_COLORS.map(rgbaCss);
const TRAIL_STYLE = `rgba(${TRAIL_COLOR[0]}, ${TRAIL_COLOR[1]}, ${TRAIL_COLOR[2]}, ${TRAIL_COLOR[3]})`;

export interface Renderer {
  name: "webgl2" | "canvas2d";
  resize(width: number, height: number, dpr: number): void;
  draw(frame: Frame): void;
  dispose(): void;
}

export function createCanvas2DRenderer(canvas: AnyCanvas): Renderer | null {
  const ctx = canvas.getContext("2d") as Ctx2D | null;
  if (!ctx) return null;
  const glow = makeGlowSprite();
  let dpr = 1;
  let linkWidth = LINK_WIDTH_DEVICE_PX;
  let linkOrder = new Int32Array(16384);
  let nodeOrder = new Int32Array(4096);
  const linkStart = new Int32Array(LINK_CODES + 1);
  const nodeStart = new Int32Array(NODE_CODES + 1);

  return {
    name: "canvas2d",
    resize(width, height, nextDpr) {
      dpr = nextDpr;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // every link is just under one device pixel at any DPR: consistently
      // visible, and always on the GPU's cheap hairline path (a wider stroke of
      // a canvas-spanning path falls back to an area-scaled software mask)
      linkWidth = LINK_WIDTH_DEVICE_PX / dpr;
    },
    draw(frame) {
      const { width, height } = frame;
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.clearRect(0, 0, width, height);

      // links: counting-sorted by style code, one reused context path per code
      const L = frame.links;
      const [lax, lay, lbx, lby, lcx, lcy, lcode, lcurved] = L.cols;
      if (linkOrder.length < L.count) linkOrder = new Int32Array(L.cap);
      linkStart.fill(0);
      for (let e = 0; e < L.count; e++) linkStart[lcode[e] + 1]++;
      for (let c = 0; c < LINK_CODES; c++) linkStart[c + 1] += linkStart[c];
      {
        const fill = linkStart.slice(0, LINK_CODES);
        for (let e = 0; e < L.count; e++) linkOrder[fill[lcode[e]]++] = e;
      }
      for (let code = 0; code < LINK_CODES; code++) {
        const from = linkStart[code];
        const to = linkStart[code + 1];
        if (from === to) continue;
        ctx.beginPath();
        for (let k = from; k < to; k++) {
          const e = linkOrder[k];
          ctx.moveTo(lax[e], lay[e]);
          if (lcurved[e]) ctx.quadraticCurveTo(lcx[e], lcy[e], lbx[e], lby[e]);
          else ctx.lineTo(lbx[e], lby[e]);
        }
        ctx.lineWidth = linkWidth;
        ctx.strokeStyle = LINK_STYLES[code];
        ctx.stroke();
      }

      // steady soft halo under every major node: textured sprite quads.
      // (Never one canvas-spanning path of many circles: a filled path that
      // wide can't be GPU-atlased and falls back to a software mask whose
      // cost scales with canvas area, which halves the frame rate at 2x DPR.)
      if (glow) {
        const H = frame.halos;
        const [hx, hy, hs] = H.cols;
        ctx.globalAlpha = HALO_ALPHA;
        for (let k = 0; k < H.count; k++) ctx.drawImage(glow, hx[k] - hs[k] / 2, hy[k] - hs[k] / 2, hs[k], hs[k]);
        ctx.globalAlpha = 1;
      }

      // nodes: counting-sorted by style code so each code sets its fill once.
      // Tiny nodes are rects (indistinguishable from circles at this size);
      // majors are individual small circles -- each shape keeps small bounds.
      const N = frame.nodes;
      const [nx, ny, nr, ncode] = N.cols;
      if (nodeOrder.length < N.count) nodeOrder = new Int32Array(N.cap);
      nodeStart.fill(0);
      for (let i = 0; i < N.count; i++) nodeStart[ncode[i] + 1]++;
      for (let c = 0; c < NODE_CODES; c++) nodeStart[c + 1] += nodeStart[c];
      {
        const fill = nodeStart.slice(0, NODE_CODES);
        for (let i = 0; i < N.count; i++) nodeOrder[fill[ncode[i]]++] = i;
      }
      for (let code = 0; code < NODE_CODES; code++) {
        const from = nodeStart[code];
        const to = nodeStart[code + 1];
        if (from === to) continue;
        const isMajor = code >= NODE_BUCKETS;
        ctx.fillStyle = NODE_STYLES[code];
        for (let k = from; k < to; k++) {
          const i = nodeOrder[k];
          const r = nr[i];
          if (isMajor) {
            ctx.beginPath();
            ctx.arc(nx[i], ny[i], r, 0, TAU);
            ctx.fill();
          } else {
            ctx.fillRect(nx[i] - r, ny[i] - r, r * 2, r * 2);
          }
        }
      }

      // pulse trails, then additive bloom on flashing nodes and pulse heads
      const D = frame.dots;
      const [dx, dy, dr] = D.cols;
      ctx.fillStyle = TRAIL_STYLE;
      for (let k = 0; k < D.count; k++) {
        ctx.beginPath();
        ctx.arc(dx[k], dy[k], dr[k], 0, TAU);
        ctx.fill();
      }
      if (glow) {
        const G = frame.glows;
        const [gx, gy, gs, ga] = G.cols;
        ctx.globalCompositeOperation = "lighter";
        for (let k = 0; k < G.count; k++) {
          ctx.globalAlpha = ga[k];
          ctx.drawImage(glow, gx[k] - gs[k] / 2, gy[k] - gs[k] / 2, gs[k], gs[k]);
        }
        ctx.globalAlpha = 1;
        ctx.globalCompositeOperation = "source-over";
      }
    },
    dispose() {},
  };
}
