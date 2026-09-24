/* The constellation's simulation: node placement, flow-field drift,
 * distance-based links, and the activation pulses that ride the backbone.
 * Renderer-agnostic and DOM-free, so it runs the same on the main thread or
 * inside a worker. Each `step()` fills one reused `Frame` of draw data (all
 * positions in CSS pixels, parallax applied, off-screen items dropped) that
 * the Canvas 2D and WebGL renderers draw identically. */

export const TAU = Math.PI * 2;
const SPEED_MULT = 2.6;

// Link classes. 0 = local mesh: any two nodes, short, straight. 1 = backbone:
// major-to-major only, medium length, gently curved.
export const LINK_DIST = [40, 104];
const LINK_SOFT_DEGREE = [7, 6];
const LINK_MAX_ALPHA = [0.46, 0.62];
const LINK_RGB: [number, number, number][] = [
  [70, 190, 240],
  [34, 211, 238],
];
export const ALPHA_BUCKETS = 6;
export const LINK_CODES = 2 * ALPHA_BUCKETS;
export const NODE_BUCKETS = 4;
export const NODE_CODES = 2 * NODE_BUCKETS;
const MAJOR_FRACTION = 0.09;
// Wider than the backbone link distance, so wrap-around always happens off-screen.
const WORLD_MARGIN = 116;
// One cell covers the local distance and two cover the backbone distance.
const GRID_CELL = 52;
const ADJ_CAP = 10;
const PULSE_PX_PER_SEC = 58 * SPEED_MULT;
const ACTIVATION_DECAY = 1.6;

export type Rgba = readonly [number, number, number, number];

// Colours are rounded to three decimals exactly as the Canvas 2D style
// strings are, so both renderers use the same values.
const round3 = (v: number) => Number(v.toFixed(3));

/** Link colour per code (class x alpha bucket). */
export const LINK_COLORS: Rgba[] = LINK_RGB.flatMap(([r, g, b], cls) =>
  Array.from({ length: ALPHA_BUCKETS }, (_, k) => [r, g, b, round3((LINK_MAX_ALPHA[cls] * (k + 1)) / ALPHA_BUCKETS)] as const),
);
/** Node colour per code: minor buckets first, then major buckets. */
export const NODE_COLORS: Rgba[] = [
  ...Array.from({ length: NODE_BUCKETS }, (_, k) => [34, 211, 238, round3(0.35 + (0.55 * (k + 0.5)) / NODE_BUCKETS)] as const),
  ...Array.from({ length: NODE_BUCKETS }, (_, k) => [60, 225, 245, round3(0.6 + (0.4 * (k + 0.5)) / NODE_BUCKETS)] as const),
];
export const TRAIL_COLOR: Rgba = [150, 240, 252, 0.55];
/** Steady halo under every major node: glow sprite at this opacity. */
export const HALO_ALPHA = 0.24;
export const HEAD_GLOW_SIZE = 14;
const HEAD_GLOW_ALPHA = 0.95;

export const rgbaCss = ([r, g, b, a]: Rgba) => `rgba(${r}, ${g}, ${b}, ${a.toFixed(3)})`;

/** Mesh links are drawn just under one device pixel wide at any DPR. */
export const LINK_WIDTH_DEVICE_PX = 0.95;

/** The glow sprite's radial gradient stops (offset, colour). */
export const GLOW_STOPS: [number, Rgba][] = [
  [0, [150, 240, 252, 0.95]],
  [0.18, [34, 211, 238, 0.55]],
  [0.5, [34, 211, 238, 0.14]],
  [1, [34, 211, 238, 0]],
];

// Deterministic per pair, so a backbone curve never changes shape between frames.
function pairBend(lo: number, hi: number): number {
  const h = (Math.imul(lo, 73856093) ^ Math.imul(hi, 19349663)) >>> 0;
  return ((h % 1024) / 1024 - 0.5) * 0.24;
}

/** A small seeded PRNG (mulberry32), for reproducible renders in tests. */
export function seededRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
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

/** Growable struct-of-arrays buffer for one kind of draw item. The push
 * methods take fixed arguments (no rest array) so filling a frame allocates
 * nothing. */
export class Items {
  count = 0;
  cap: number;
  cols: Float32Array[];
  constructor(columns: number, cap = 256) {
    this.cap = cap;
    this.cols = Array.from({ length: columns }, () => new Float32Array(cap));
  }
  private slot(): number {
    if (this.count === this.cap) {
      this.cap *= 2;
      this.cols = this.cols.map((c) => {
        const next = new Float32Array(this.cap);
        next.set(c);
        return next;
      });
    }
    return this.count++;
  }
  push3(a: number, b: number, c: number) {
    const k = this.slot();
    const cols = this.cols;
    cols[0][k] = a;
    cols[1][k] = b;
    cols[2][k] = c;
  }
  push4(a: number, b: number, c: number, d: number) {
    const k = this.slot();
    const cols = this.cols;
    cols[0][k] = a;
    cols[1][k] = b;
    cols[2][k] = c;
    cols[3][k] = d;
  }
  push8(a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number) {
    const k = this.slot();
    const cols = this.cols;
    cols[0][k] = a;
    cols[1][k] = b;
    cols[2][k] = c;
    cols[3][k] = d;
    cols[4][k] = e;
    cols[5][k] = f;
    cols[6][k] = g;
    cols[7][k] = h;
  }
}

/** One frame of draw data, in draw order. Columns per item kind:
 * - links:  ax, ay, bx, by, cx, cy (quadratic control point), code, curved (0/1)
 * - halos:  x, y, size
 * - nodes:  x, y, r, code (>= NODE_BUCKETS means a major node: a circle; else a square)
 * - dots:   x, y, r (pulse trail dots)
 * - glows:  x, y, size, alpha (additive; activated majors, then pulse heads) */
export interface Frame {
  width: number;
  height: number;
  links: Items;
  halos: Items;
  nodes: Items;
  dots: Items;
  glows: Items;
}

export interface Field {
  frame: Frame;
  /** Rebuild the whole field for a new viewport size. */
  build(width: number, height: number): void;
  /** Advance by `dt` seconds of motion (0 for a still frame) and fill `frame`. */
  step(now: number, dt: number, pointer: { x: number; y: number }): Frame;
}

export function createField(random: () => number = Math.random): Field {
  let width = 0;
  let height = 0;
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

  let worldW = 0;
  let worldH = 0;
  let flow: FlowWave[] = [];
  let pulses: Pulse[] = [];
  let maxPulses = 0;
  let pulseRate = 0;
  let pulseAccum = 0;

  const frame: Frame = {
    width: 0,
    height: 0,
    links: new Items(8, 16384),
    halos: new Items(3),
    nodes: new Items(4, 4096),
    dots: new Items(3),
    glows: new Items(4),
  };

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
  }

  function build(w: number, h: number) {
    width = w;
    height = h;
    const isMobile = width < 640;
    worldW = width + WORLD_MARGIN * 2;
    worldH = height + WORLD_MARGIN * 2;
    const areaPerNode = isMobile ? 680 : 600;
    const target = Math.max(60, Math.min(isMobile ? 1000 : 3400, Math.round((worldW * worldH) / areaPerNode)));

    // a smooth irregular density field: overlapping denser local networks,
    // with a high floor so no region ever reads as an empty gap
    const bumps = Array.from({ length: isMobile ? 6 : 10 }, () => ({
      x: random() * worldW - WORLD_MARGIN,
      y: random() * worldH - WORLD_MARGIN,
      s: (isMobile ? 90 : 140) + random() * (isMobile ? 120 : 200),
      a: 0.5 + random() * 0.6,
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
      const x = random() * worldW - WORLD_MARGIN;
      const y = random() * worldH - WORLD_MARGIN;
      let f = 0;
      for (const b of bumps) {
        const dx = x - b.x;
        const dy = y - b.y;
        f += b.a * Math.exp(-(dx * dx + dy * dy) / (2 * b.s * b.s));
      }
      if (random() > floor + (1 - floor) * Math.min(1, f)) continue;
      const i = placed++;
      const isMajor = random() < MAJOR_FRACTION;
      const ang = random() * TAU;
      const sp = (0.3 + random() * 0.7) * SPEED_MULT;
      px[i] = x;
      py[i] = y;
      driftX[i] = Math.cos(ang) * sp;
      driftY[i] = Math.sin(ang) * sp;
      major[i] = isMajor ? 1 : 0;
      radius[i] = isMajor ? 2.7 + random() * 1.3 : 0.65 + random() * 0.6;
      bright[i] = isMajor ? 0.7 + random() * 0.3 : 0.35 + random() * 0.5;
      twPhase[i] = random() * TAU;
      twSpeed[i] = (0.25 + random() * 0.5) * SPEED_MULT;
    }
    n = placed;
    degree = new Uint16Array(n * 2);

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
      const ang = random() * TAU;
      return {
        ux: Math.cos(ang),
        uy: Math.sin(ang),
        k: TAU / (520 + random() * 640),
        w: (0.03 + random() * 0.035) * SPEED_MULT,
        phi: random() * TAU,
        s: (2.9 + random() * 1) * SPEED_MULT,
      };
    });

    pulses = [];
    pulseAccum = 0;
    maxPulses = isMobile ? 8 : 18;
    pulseRate = isMobile ? 1.4 : 3.2;
  }

  function step(now: number, dt: number, pointer: { x: number; y: number }): Frame {
    const t = now / 1000;
    const parX = (pointer.x - 0.5) * 10;
    const parY = (pointer.y - 0.5) * 10;
    const moving = dt > 0;

    // 1. advect every node along the slowly evolving divergence-free flow
    if (moving) {
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

    // 3. collect every link in range this frame, counting per-node degree.
    // Each node scans only the forward half of its neighbourhood (its own
    // cell, then later cells in raster order), so every pair is visited
    // exactly once: from the node in the earlier cell. That node's range
    // always reaches the pair -- local links span at most one cell, and a
    // backbone pair is two majors, which scan two cells out.
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
      for (let dy = 0; dy <= range; dy++) {
        const gy = cy + dy;
        if (gy >= gridRows) break;
        for (let dx = dy === 0 ? 0 : -range; dx <= range; dx++) {
          const gx = cx + dx;
          if (gx < 0 || gx >= gridCols) continue;
          const cc = gy * gridCols + gx;
          const sameCell = dy === 0 && dx === 0;
          for (let k = cellStart[cc], end = cellStart[cc + 1]; k < end; k++) {
            const j = cellItems[k];
            if (sameCell && j <= i) continue;
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
    if (moving && majors.length > 0) {
      pulseAccum += dt * pulseRate;
      while (pulseAccum >= 1) {
        pulseAccum -= 1;
        if (pulses.length >= maxPulses) continue;
        const s = (random() * majors.length) | 0;
        if (adjCount[s] === 0) continue;
        pulses.push({
          a: majors[s],
          b: adj[s * ADJ_CAP + ((random() * adjCount[s]) | 0)],
          t: 0,
          life: 3 + ((random() * 6) | 0),
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
        let next = adj[s * ADJ_CAP + ((random() * adjCount[s]) | 0)];
        if (next === p.a && adjCount[s] > 1) next = adj[s * ADJ_CAP + ((random() * adjCount[s]) | 0)];
        p.a = p.b;
        p.b = next;
        p.t = 0;
        alive.push(p);
      }
    }
    pulses = alive;

    frame.width = width;
    frame.height = height;

    // 5. links on screen, with their class x alpha-bucket style code
    const L = frame.links;
    L.count = 0;
    for (let e = 0; e < links; e++) {
      const i = linkA[e];
      const j = linkB[e];
      const ax = px[i] + parX;
      const ay = py[i] + parY;
      const bx = px[j] + parX;
      const by = py[j] + parY;
      if ((ax < 0 && bx < 0) || (ax > width && bx > width) || (ay < 0 && by < 0) || (ay > height && by > height)) continue;
      const cls = linkT[e];
      const q = linkD[e] / LINK_DIST[cls];
      // crowded nodes dim their links smoothly instead of dropping them,
      // so dense pockets never pop or flicker as neighbours come and go
      const crowd = Math.max(degree[i * 2 + cls], degree[j * 2 + cls]);
      const soft = LINK_SOFT_DEGREE[cls];
      const level = (1 - q * q) * (crowd > soft ? soft / crowd : 1);
      if (level < 0.06) continue;
      const code = cls * ALPHA_BUCKETS + Math.min(ALPHA_BUCKETS - 1, (level * ALPHA_BUCKETS) | 0);
      if (cls === 1) {
        const d = linkD[e];
        const bend = pairBend(i, j) * d;
        L.push8(ax, ay, bx, by, (ax + bx) / 2 - ((by - ay) / d) * bend, (ay + by) / 2 + ((bx - ax) / d) * bend, code, 1);
      } else {
        L.push8(ax, ay, bx, by, 0, 0, code, 0);
      }
    }

    // 6. steady soft halo under every major node
    const H = frame.halos;
    H.count = 0;
    for (let s = 0; s < majors.length; s++) {
      const i = majors[s];
      const x = px[i] + parX;
      const y = py[i] + parY;
      if (x < -20 || x > width + 20 || y < -20 || y > height + 20) continue;
      H.push3(x, y, radius[i] * 6.4);
    }

    // 7. nodes, with their size-class x brightness-bucket style code
    const N = frame.nodes;
    N.count = 0;
    for (let i = 0; i < n; i++) {
      const x = px[i] + parX;
      const y = py[i] + parY;
      if (x < -6 || x > width + 6 || y < -6 || y > height + 6) continue;
      const tw = 0.7 + 0.3 * Math.sin(t * twSpeed[i] + twPhase[i]);
      const level = Math.min(0.999, bright[i] * tw + activation[i] * 0.6);
      N.push4(x, y, radius[i] + activation[i] * 1.8, major[i] * NODE_BUCKETS + ((level * NODE_BUCKETS) | 0));
    }

    // 8. travelling pulses: a fading trail of small dots, then additive glows
    // on the nodes currently flashing and on the pulse heads
    const D = frame.dots;
    const G = frame.glows;
    D.count = 0;
    G.count = 0;
    const heads: number[] = [];
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
        if (k === 0) heads.push(x, y);
        else D.push3(x, y, 1.9 - k * 0.4);
      }
    }
    for (let s = 0; s < majors.length; s++) {
      const i = majors[s];
      const a = activation[i];
      if (a < 0.06) continue;
      const x = px[i] + parX;
      const y = py[i] + parY;
      if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;
      G.push4(x, y, radius[i] * 5 + a * 30, Math.min(1, a * 0.85));
    }
    for (let h = 0; h < heads.length; h += 2) G.push4(heads[h], heads[h + 1], HEAD_GLOW_SIZE, HEAD_GLOW_ALPHA);

    for (let s = 0; s < majors.length; s++) {
      const i = majors[s];
      if (activation[i] > 0) activation[i] = Math.max(0, activation[i] - dt * ACTIVATION_DECAY);
    }
    return frame;
  }

  return { frame, build, step };
}
