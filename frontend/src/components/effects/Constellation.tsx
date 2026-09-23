"use client";

import { useEffect, useRef } from "react";

interface ConstellationProps {
  className?: string;
}

interface Pulse {
  a: number;
  b: number;
  t: number;
  life: number;
}

interface FlowWave {
  ux: number;
  uy: number;
  k: number;
  w: number;
  phi: number;
  s: number;
}

const SPEED_MULT = 2.6;
const TAU = Math.PI * 2;

// Link classes. 0 = local mesh: any two nodes, short, straight. 1 = backbone:
// major-to-major only, medium length, gently curved.
const LINK_DIST = [40, 104];
const LINK_SOFT_DEGREE = [7, 6];
const LINK_MAX_ALPHA = [0.46, 0.62];
const LINK_RGB = ["70, 190, 240", "34, 211, 238"];
const ALPHA_BUCKETS = 6;
const LINK_CODES = 2 * ALPHA_BUCKETS;
const NODE_BUCKETS = 4;
const NODE_CODES = 2 * NODE_BUCKETS;
const SKIP = 255;
const MAJOR_FRACTION = 0.09;
// Wider than the backbone link distance, so wrap-around always happens off-screen.
const WORLD_MARGIN = 116;
// One cell covers the local distance and two cover the backbone distance.
const GRID_CELL = 52;
const ADJ_CAP = 10;
const PULSE_PX_PER_SEC = 58 * SPEED_MULT;
const ACTIVATION_DECAY = 1.6;
// Adaptive quality: if the median delivered frame interval stays above this,
// the field thins itself out (at most twice).
const SLOW_FRAME_MS = 24;
const GAP_WINDOW = 60;

const LINK_STYLES = LINK_RGB.flatMap((rgb, cls) =>
  Array.from(
    { length: ALPHA_BUCKETS },
    (_, b) => `rgba(${rgb}, ${((LINK_MAX_ALPHA[cls] * (b + 1)) / ALPHA_BUCKETS).toFixed(3)})`,
  ),
);
const NODE_STYLES = [
  ...Array.from(
    { length: NODE_BUCKETS },
    (_, b) => `rgba(34, 211, 238, ${(0.35 + (0.55 * (b + 0.5)) / NODE_BUCKETS).toFixed(3)})`,
  ),
  ...Array.from(
    { length: NODE_BUCKETS },
    (_, b) => `rgba(60, 225, 245, ${(0.6 + (0.4 * (b + 0.5)) / NODE_BUCKETS).toFixed(3)})`,
  ),
];

// Deterministic per pair, so a backbone curve never changes shape between frames.
function pairBend(lo: number, hi: number): number {
  const h = (Math.imul(lo, 73856093) ^ Math.imul(hi, 19349663)) >>> 0;
  return ((h % 1024) / 1024 - 0.5) * 0.24;
}

function makeGlowSprite(): HTMLCanvasElement | null {
  const sprite = document.createElement("canvas");
  sprite.width = 64;
  sprite.height = 64;
  const g = sprite.getContext("2d");
  if (!g) return null;
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(150, 240, 252, 0.95)");
  grad.addColorStop(0.18, "rgba(34, 211, 238, 0.55)");
  grad.addColorStop(0.5, "rgba(34, 211, 238, 0.14)");
  grad.addColorStop(1, "rgba(34, 211, 238, 0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  return sprite;
}

/** The one shared, globally-mounted research-intelligence background --
 * mounted once in the root layout, never per-page, so it survives route
 * navigation without remounting. Fixed-position and viewport-sized, so it
 * reads identically at every scroll position.
 *
 * A dense computational network field in the reference recording's visual
 * language (bold cyan nodes, thin distance-faded links, drifting motion)
 * at a much higher density than the recording itself: thousands of drifting
 * nodes whose links are recomputed every frame by distance, so connections
 * continuously form and dissolve as nodes move. Two scales of structure: a
 * fine mesh of short straight links between any nearby nodes, and a sparser
 * backbone of gently curved links between the larger, brighter "major"
 * nodes, which the travelling activation pulses ride. Placement follows a
 * smooth irregular density field with a high floor, so local networks
 * overlap and merge without gaps, and motion comes from a divergence-free
 * flow field, which swirls nodes without ever clumping them or opening holes.
 *
 * Performance: a spatial hash grid keeps neighbour search linear; links and
 * nodes are counting-sorted into a few alpha buckets and drawn with the
 * context's own reused path (no per-frame Path2D allocations, so no GC
 * stutter); mesh links stay at or under one device pixel wide so the GPU can
 * take its cheap hairline path; tiny nodes are rects rather than arcs; glow
 * sprites are only drawn for the few nodes currently flashing. If the median
 * delivered frame interval stays slow, the field thins itself out. Rebuilt
 * (debounced) on every real viewport resize. Renders one static frame and
 * never starts the loop under prefers-reduced-motion. */
export default function Constellation({ className }: ConstellationProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const glow = makeGlowSprite();

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    // every link is just under one device pixel at any DPR: consistently
    // visible, and always on the GPU's cheap hairline path (a wider stroke of
    // a canvas-spanning path falls back to an area-scaled software mask)
    const linkWidth = 0.95 / dpr;
    const pointer = { x: 0.5, y: 0.4, tx: 0.5, ty: 0.4 };

    let width = 0;
    let height = 0;
    function resizeCanvas() {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas!.width = width * dpr;
      canvas!.height = height * dpr;
      canvas!.style.width = `${width}px`;
      canvas!.style.height = `${height}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resizeCanvas();

    let n = 0;
    let px = new Float32Array(0);
    let py = new Float32Array(0);
    let driftX = new Float32Array(0);
    let driftY = new Float32Array(0);
    let radius = new Float32Array(0);
    let bright = new Float32Array(0);
    let twPhase = new Float32Array(0);
    let twSpeed = new Float32Array(0);
    let activation = new Float32Array(0);
    let major = new Uint8Array(0);
    let majorSlot = new Int32Array(0);
    let majors = new Int32Array(0);
    let adj = new Int32Array(0);
    let adjCount = new Uint8Array(0);
    let degree = new Uint16Array(0);
    let nodeCode = new Uint8Array(0);
    let nodeOrder = new Int32Array(0);
    const nodeStart = new Int32Array(NODE_CODES + 1);

    let gridCols = 0;
    let gridRows = 0;
    let cellOf = new Int32Array(0);
    let cellStart = new Int32Array(0);
    let cellFill = new Int32Array(0);
    let cellItems = new Int32Array(0);

    let linkCap = 16384;
    let linkA = new Int32Array(linkCap);
    let linkB = new Int32Array(linkCap);
    let linkD = new Float32Array(linkCap);
    let linkT = new Uint8Array(linkCap);
    let linkCode = new Uint8Array(linkCap);
    let linkOrder = new Int32Array(linkCap);
    const linkStart = new Int32Array(LINK_CODES + 1);

    let worldW = 0;
    let worldH = 0;
    let flow: FlowWave[] = [];
    let pulses: Pulse[] = [];
    let maxPulses = 0;
    let pulseRate = 0;
    let pulseAccum = 0;
    let densityScale = 1;
    let downgrades = 0;
    let framesSinceBuild = 0;
    const recentGaps = new Float32Array(GAP_WINDOW);
    let gapCount = 0;
    let gapIdx = 0;

    function growLinks() {
      linkCap *= 2;
      const a = new Int32Array(linkCap);
      a.set(linkA);
      linkA = a;
      const b = new Int32Array(linkCap);
      b.set(linkB);
      linkB = b;
      const d = new Float32Array(linkCap);
      d.set(linkD);
      linkD = d;
      const t = new Uint8Array(linkCap);
      t.set(linkT);
      linkT = t;
      linkCode = new Uint8Array(linkCap);
      linkOrder = new Int32Array(linkCap);
    }

    function buildField() {
      const isMobile = width < 640;
      worldW = width + WORLD_MARGIN * 2;
      worldH = height + WORLD_MARGIN * 2;
      const areaPerNode = isMobile ? 680 : 600;
      const target = Math.max(
        60,
        Math.min(isMobile ? 1000 : 3400, Math.round(((worldW * worldH) / areaPerNode) * densityScale)),
      );

      // a smooth irregular density field: overlapping denser local networks,
      // with a high floor so no region ever reads as an empty gap
      const bumps = Array.from({ length: isMobile ? 6 : 10 }, () => ({
        x: Math.random() * worldW - WORLD_MARGIN,
        y: Math.random() * worldH - WORLD_MARGIN,
        s: (isMobile ? 90 : 140) + Math.random() * (isMobile ? 120 : 200),
        a: 0.5 + Math.random() * 0.6,
      }));
      const floor = 0.45;

      px = new Float32Array(target);
      py = new Float32Array(target);
      driftX = new Float32Array(target);
      driftY = new Float32Array(target);
      radius = new Float32Array(target);
      bright = new Float32Array(target);
      twPhase = new Float32Array(target);
      twSpeed = new Float32Array(target);
      activation = new Float32Array(target);
      major = new Uint8Array(target);

      let placed = 0;
      for (let guard = 0; placed < target && guard < target * 40; guard++) {
        const x = Math.random() * worldW - WORLD_MARGIN;
        const y = Math.random() * worldH - WORLD_MARGIN;
        let f = 0;
        for (const b of bumps) {
          const dx = x - b.x;
          const dy = y - b.y;
          f += b.a * Math.exp(-(dx * dx + dy * dy) / (2 * b.s * b.s));
        }
        if (Math.random() > floor + (1 - floor) * Math.min(1, f)) continue;
        const i = placed++;
        const isMajor = Math.random() < MAJOR_FRACTION;
        const ang = Math.random() * TAU;
        const sp = (0.3 + Math.random() * 0.7) * SPEED_MULT;
        px[i] = x;
        py[i] = y;
        driftX[i] = Math.cos(ang) * sp;
        driftY[i] = Math.sin(ang) * sp;
        major[i] = isMajor ? 1 : 0;
        radius[i] = isMajor ? 2.7 + Math.random() * 1.3 : 0.65 + Math.random() * 0.6;
        bright[i] = isMajor ? 0.7 + Math.random() * 0.3 : 0.35 + Math.random() * 0.5;
        twPhase[i] = Math.random() * TAU;
        twSpeed[i] = (0.25 + Math.random() * 0.5) * SPEED_MULT;
      }
      n = placed;
      degree = new Uint16Array(n * 2);
      nodeCode = new Uint8Array(n);
      nodeOrder = new Int32Array(n);

      let majorCount = 0;
      for (let i = 0; i < n; i++) majorCount += major[i];
      majors = new Int32Array(majorCount);
      majorSlot = new Int32Array(n).fill(-1);
      for (let i = 0, s = 0; i < n; i++) {
        if (!major[i]) continue;
        majors[s] = i;
        majorSlot[i] = s++;
      }
      adj = new Int32Array(majorCount * ADJ_CAP);
      adjCount = new Uint8Array(majorCount);

      gridCols = Math.ceil(worldW / GRID_CELL);
      gridRows = Math.ceil(worldH / GRID_CELL);
      cellStart = new Int32Array(gridCols * gridRows + 1);
      cellFill = new Int32Array(gridCols * gridRows);
      cellOf = new Int32Array(n);
      cellItems = new Int32Array(n);

      flow = Array.from({ length: 3 }, () => {
        const ang = Math.random() * TAU;
        return {
          ux: Math.cos(ang),
          uy: Math.sin(ang),
          k: TAU / (520 + Math.random() * 640),
          w: (0.03 + Math.random() * 0.035) * SPEED_MULT,
          phi: Math.random() * TAU,
          s: (2.9 + Math.random() * 1) * SPEED_MULT,
        };
      });

      pulses = [];
      pulseAccum = 0;
      maxPulses = isMobile ? 8 : 18;
      pulseRate = isMobile ? 1.4 : 3.2;
      framesSinceBuild = 0;
      gapCount = 0;
      gapIdx = 0;
    }
    buildField();

    let resizeSettleTimer: ReturnType<typeof setTimeout> | null = null;
    function handleResize() {
      resizeCanvas();
      if (resizeSettleTimer) clearTimeout(resizeSettleTimer);
      resizeSettleTimer = setTimeout(buildField, 200);
    }

    function handlePointerMove(e: PointerEvent) {
      pointer.tx = e.clientX / window.innerWidth;
      pointer.ty = e.clientY / window.innerHeight;
    }
    window.addEventListener("resize", handleResize);
    window.addEventListener("pointermove", handlePointerMove);

    let raf = 0;
    let last = performance.now();

    function frame(now: number) {
      const gap = now - last;
      const dt = Math.min(gap / 1000, 0.05);
      last = now;
      const t = now / 1000;

      pointer.x += (pointer.tx - pointer.x) * 0.02;
      pointer.y += (pointer.ty - pointer.y) * 0.02;
      const parX = (pointer.x - 0.5) * 10;
      const parY = (pointer.y - 0.5) * 10;

      // 1. advect every node along the slowly evolving divergence-free flow
      if (!reduceMotion) {
        for (let i = 0; i < n; i++) {
          const x = px[i];
          const y = py[i];
          let vx = driftX[i];
          let vy = driftY[i];
          for (let w = 0; w < flow.length; w++) {
            const f = flow[w];
            const c = Math.cos(f.k * (f.ux * x + f.uy * y) + f.w * t + f.phi) * f.s;
            vx += c * f.uy;
            vy -= c * f.ux;
          }
          let nx = x + vx * dt;
          let ny = y + vy * dt;
          if (nx < -WORLD_MARGIN) nx += worldW;
          else if (nx >= worldW - WORLD_MARGIN) nx -= worldW;
          if (ny < -WORLD_MARGIN) ny += worldH;
          else if (ny >= worldH - WORLD_MARGIN) ny -= worldH;
          px[i] = nx;
          py[i] = ny;
        }
      }

      // 2. bucket nodes into the spatial grid
      const cellCount = gridCols * gridRows;
      cellStart.fill(0);
      for (let i = 0; i < n; i++) {
        let gx = ((px[i] + WORLD_MARGIN) / GRID_CELL) | 0;
        let gy = ((py[i] + WORLD_MARGIN) / GRID_CELL) | 0;
        if (gx < 0) gx = 0;
        else if (gx >= gridCols) gx = gridCols - 1;
        if (gy < 0) gy = 0;
        else if (gy >= gridRows) gy = gridRows - 1;
        const c = gy * gridCols + gx;
        cellOf[i] = c;
        cellStart[c + 1]++;
      }
      for (let c = 0; c < cellCount; c++) cellStart[c + 1] += cellStart[c];
      cellFill.set(cellStart.subarray(0, cellCount));
      for (let i = 0; i < n; i++) cellItems[cellFill[cellOf[i]]++] = i;

      // 3. collect every link in range this frame, counting per-node degree
      degree.fill(0);
      adjCount.fill(0);
      const local2 = LINK_DIST[0] * LINK_DIST[0];
      const backbone2 = LINK_DIST[1] * LINK_DIST[1];
      let links = 0;
      for (let i = 0; i < n; i++) {
        const xi = px[i];
        const yi = py[i];
        const mi = major[i];
        const range = mi ? 2 : 1;
        const c = cellOf[i];
        const cx = c % gridCols;
        const cy = (c - cx) / gridCols;
        const gx0 = Math.max(0, cx - range);
        const gx1 = Math.min(gridCols - 1, cx + range);
        const gy0 = Math.max(0, cy - range);
        const gy1 = Math.min(gridRows - 1, cy + range);
        for (let gy = gy0; gy <= gy1; gy++) {
          for (let gx = gx0; gx <= gx1; gx++) {
            const cc = gy * gridCols + gx;
            for (let k = cellStart[cc], end = cellStart[cc + 1]; k < end; k++) {
              const j = cellItems[k];
              if (j <= i) continue;
              const dx = px[j] - xi;
              const dy = py[j] - yi;
              const d2 = dx * dx + dy * dy;
              let cls: number;
              if (d2 < local2) cls = 0;
              else if (mi & major[j] && d2 < backbone2) cls = 1;
              else continue;
              if (links >= linkCap) growLinks();
              linkA[links] = i;
              linkB[links] = j;
              linkD[links] = Math.sqrt(d2);
              linkT[links] = cls;
              links++;
              degree[i * 2 + cls]++;
              degree[j * 2 + cls]++;
              if (cls === 1) {
                const si = majorSlot[i];
                const sj = majorSlot[j];
                if (adjCount[si] < ADJ_CAP) adj[si * ADJ_CAP + adjCount[si]++] = j;
                if (adjCount[sj] < ADJ_CAP) adj[sj * ADJ_CAP + adjCount[sj]++] = i;
              }
            }
          }
        }
      }

      // 4. pulses: activations riding the curved backbone, hop by hop
      if (!reduceMotion && majors.length > 0) {
        pulseAccum += dt * pulseRate;
        while (pulseAccum >= 1) {
          pulseAccum -= 1;
          if (pulses.length >= maxPulses) continue;
          const s = (Math.random() * majors.length) | 0;
          if (adjCount[s] === 0) continue;
          pulses.push({
            a: majors[s],
            b: adj[s * ADJ_CAP + ((Math.random() * adjCount[s]) | 0)],
            t: 0,
            life: 3 + ((Math.random() * 6) | 0),
          });
        }
      }
      const alive: Pulse[] = [];
      for (const p of pulses) {
        const d = Math.hypot(px[p.b] - px[p.a], py[p.b] - py[p.a]);
        // endpoints drifted apart, or one of them wrapped around the world
        if (d > LINK_DIST[1] * 1.5) continue;
        p.t += (dt * PULSE_PX_PER_SEC) / Math.max(d, 8);
        if (p.t < 1) {
          alive.push(p);
          continue;
        }
        activation[p.b] = 1;
        const s = majorSlot[p.b];
        p.life--;
        if (p.life > 0 && adjCount[s] > 0) {
          let next = adj[s * ADJ_CAP + ((Math.random() * adjCount[s]) | 0)];
          if (next === p.a && adjCount[s] > 1) next = adj[s * ADJ_CAP + ((Math.random() * adjCount[s]) | 0)];
          p.a = p.b;
          p.b = next;
          p.t = 0;
          alive.push(p);
        }
      }
      pulses = alive;

      ctx!.globalCompositeOperation = "source-over";
      ctx!.globalAlpha = 1;
      ctx!.clearRect(0, 0, width, height);

      // 5. links: counting-sorted by class x alpha bucket, then drawn with
      // one reused context path per bucket
      linkStart.fill(0);
      for (let e = 0; e < links; e++) {
        const i = linkA[e];
        const j = linkB[e];
        const ax = px[i] + parX;
        const ay = py[i] + parY;
        const bx = px[j] + parX;
        const by = py[j] + parY;
        if (
          (ax < 0 && bx < 0) ||
          (ax > width && bx > width) ||
          (ay < 0 && by < 0) ||
          (ay > height && by > height)
        ) {
          linkCode[e] = SKIP;
          continue;
        }
        const cls = linkT[e];
        const q = linkD[e] / LINK_DIST[cls];
        // crowded nodes dim their links smoothly instead of dropping them,
        // so dense pockets never pop or flicker as neighbours come and go
        const crowd = Math.max(degree[i * 2 + cls], degree[j * 2 + cls]);
        const soft = LINK_SOFT_DEGREE[cls];
        const level = (1 - q * q) * (crowd > soft ? soft / crowd : 1);
        if (level < 0.06) {
          linkCode[e] = SKIP;
          continue;
        }
        const code = cls * ALPHA_BUCKETS + Math.min(ALPHA_BUCKETS - 1, (level * ALPHA_BUCKETS) | 0);
        linkCode[e] = code;
        linkStart[code + 1]++;
      }
      for (let c = 0; c < LINK_CODES; c++) linkStart[c + 1] += linkStart[c];
      {
        const fill = linkStart.slice(0, LINK_CODES);
        for (let e = 0; e < links; e++) {
          const code = linkCode[e];
          if (code !== SKIP) linkOrder[fill[code]++] = e;
        }
      }
      for (let code = 0; code < LINK_CODES; code++) {
        const from = linkStart[code];
        const to = linkStart[code + 1];
        if (from === to) continue;
        const cls = code >= ALPHA_BUCKETS ? 1 : 0;
        ctx!.beginPath();
        for (let k = from; k < to; k++) {
          const e = linkOrder[k];
          const i = linkA[e];
          const j = linkB[e];
          const ax = px[i] + parX;
          const ay = py[i] + parY;
          const bx = px[j] + parX;
          const by = py[j] + parY;
          ctx!.moveTo(ax, ay);
          if (cls === 1) {
            const d = linkD[e];
            const bend = pairBend(i, j) * d;
            ctx!.quadraticCurveTo(
              (ax + bx) / 2 - ((by - ay) / d) * bend,
              (ay + by) / 2 + ((bx - ax) / d) * bend,
              bx,
              by,
            );
          } else {
            ctx!.lineTo(bx, by);
          }
        }
        ctx!.lineWidth = linkWidth;
        ctx!.strokeStyle = LINK_STYLES[code];
        ctx!.stroke();
      }

      // 6. steady soft halo under every major node: textured sprite quads.
      // (Never one canvas-spanning path of many circles: a filled path that
      // wide can't be GPU-atlased and falls back to a software mask whose
      // cost scales with canvas area, which halves the frame rate at 2x DPR.)
      if (glow) {
        ctx!.globalAlpha = 0.24;
        for (let s = 0; s < majors.length; s++) {
          const i = majors[s];
          const x = px[i] + parX;
          const y = py[i] + parY;
          if (x < -20 || x > width + 20 || y < -20 || y > height + 20) continue;
          const size = radius[i] * 6.4;
          ctx!.drawImage(glow, x - size / 2, y - size / 2, size, size);
        }
        ctx!.globalAlpha = 1;
      }

      // 7. nodes: counting-sorted by size class x brightness bucket so each
      // bucket sets its fill style once. Tiny nodes are individual rects
      // (indistinguishable from circles at this size, and batched trivially
      // by the GPU); majors are individual small circles -- each shape keeps
      // small bounds, never one path spanning the canvas.
      nodeStart.fill(0);
      for (let i = 0; i < n; i++) {
        const x = px[i] + parX;
        const y = py[i] + parY;
        if (x < -6 || x > width + 6 || y < -6 || y > height + 6) {
          nodeCode[i] = SKIP;
          continue;
        }
        const tw = 0.7 + 0.3 * Math.sin(t * twSpeed[i] + twPhase[i]);
        const level = Math.min(0.999, bright[i] * tw + activation[i] * 0.6);
        const code = major[i] * NODE_BUCKETS + ((level * NODE_BUCKETS) | 0);
        nodeCode[i] = code;
        nodeStart[code + 1]++;
      }
      for (let c = 0; c < NODE_CODES; c++) nodeStart[c + 1] += nodeStart[c];
      {
        const fill = nodeStart.slice(0, NODE_CODES);
        for (let i = 0; i < n; i++) {
          const code = nodeCode[i];
          if (code !== SKIP) nodeOrder[fill[code]++] = i;
        }
      }
      for (let code = 0; code < NODE_CODES; code++) {
        const from = nodeStart[code];
        const to = nodeStart[code + 1];
        if (from === to) continue;
        const isMajor = code >= NODE_BUCKETS;
        ctx!.fillStyle = NODE_STYLES[code];
        for (let k = from; k < to; k++) {
          const i = nodeOrder[k];
          const x = px[i] + parX;
          const y = py[i] + parY;
          const r = radius[i] + activation[i] * 1.8;
          if (isMajor) {
            ctx!.beginPath();
            ctx!.arc(x, y, r, 0, TAU);
            ctx!.fill();
          } else {
            ctx!.fillRect(x - r, y - r, r * 2, r * 2);
          }
        }
      }

      // 8. travelling pulses: a fading trail of small dots, then an additive
      // bloom sprite on only the pulse heads and the nodes currently flashing
      const heads: number[] = [];
      ctx!.fillStyle = "rgba(150, 240, 252, 0.55)";
      for (const p of pulses) {
        const lo = Math.min(p.a, p.b);
        const hi = Math.max(p.a, p.b);
        const ax = px[lo] + parX;
        const ay = py[lo] + parY;
        const bx = px[hi] + parX;
        const by = py[hi] + parY;
        const d = Math.hypot(bx - ax, by - ay) || 1;
        // match whichever shape this pair is drawn with this frame
        const bend = d >= LINK_DIST[0] ? pairBend(lo, hi) * d : 0;
        const cx = (ax + bx) / 2 - ((by - ay) / d) * bend;
        const cy = (ay + by) / 2 + ((bx - ax) / d) * bend;
        for (let k = 0; k < 4; k++) {
          const tt = p.t - k * 0.06;
          if (tt < 0) break;
          const u = p.a === lo ? tt : 1 - tt;
          const iu = 1 - u;
          const x = iu * iu * ax + 2 * iu * u * cx + u * u * bx;
          const y = iu * iu * ay + 2 * iu * u * cy + u * u * by;
          if (k === 0) {
            heads.push(x, y);
          } else {
            const r = 1.9 - k * 0.4;
            ctx!.beginPath();
            ctx!.arc(x, y, r, 0, TAU);
            ctx!.fill();
          }
        }
      }
      if (glow) {
        ctx!.globalCompositeOperation = "lighter";
        for (let s = 0; s < majors.length; s++) {
          const i = majors[s];
          const a = activation[i];
          if (a < 0.06) continue;
          const x = px[i] + parX;
          const y = py[i] + parY;
          if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;
          const size = radius[i] * 5 + a * 30;
          ctx!.globalAlpha = Math.min(1, a * 0.85);
          ctx!.drawImage(glow, x - size / 2, y - size / 2, size, size);
        }
        ctx!.globalAlpha = 0.95;
        for (let h = 0; h < heads.length; h += 2) {
          ctx!.drawImage(glow, heads[h] - 7, heads[h + 1] - 7, 14, 14);
        }
        ctx!.globalAlpha = 1;
        ctx!.globalCompositeOperation = "source-over";
      }
      for (let s = 0; s < majors.length; s++) {
        const i = majors[s];
        if (activation[i] > 0) activation[i] = Math.max(0, activation[i] - dt * ACTIVATION_DECAY);
      }

      // thin the field out if frames are consistently arriving slowly;
      // gaps over 100ms are tab switches or throttling, not real cost
      if (gap > 0 && gap < 100) {
        recentGaps[gapIdx] = gap;
        gapIdx = (gapIdx + 1) % GAP_WINDOW;
        if (gapCount < GAP_WINDOW) gapCount++;
      }
      framesSinceBuild++;
      if (!reduceMotion && downgrades < 2 && framesSinceBuild > 150 && gapCount === GAP_WINDOW) {
        const sorted = Array.from(recentGaps).sort((a, b) => a - b);
        if (sorted[GAP_WINDOW >> 1] > SLOW_FRAME_MS) {
          downgrades++;
          densityScale *= 0.7;
          buildField();
        }
      }

      if (!reduceMotion) raf = requestAnimationFrame(frame);
    }

    if (reduceMotion) {
      frame(performance.now());
    } else {
      raf = requestAnimationFrame(frame);
    }

    return () => {
      cancelAnimationFrame(raf);
      if (resizeSettleTimer) clearTimeout(resizeSettleTimer);
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("pointermove", handlePointerMove);
    };
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden />;
}
