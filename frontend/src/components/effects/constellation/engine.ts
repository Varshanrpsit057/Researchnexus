/* Runs the constellation: one field, one renderer, one frame loop. The same
 * code runs inside the worker (on an OffscreenCanvas) or on the main thread.
 *
 * Frame pacing is what keeps it light without changing how it looks:
 * - It renders at most ~60 times a second. On a 120/144 Hz display the
 *   browser offers twice as many frames; motion is time-based, so drawing
 *   every other one looks the same at half the cost.
 * - If frames still arrive slowly (median render interval over SLOW_FRAME_MS),
 *   it steps down to ~30 fps. The field itself -- node count, links, glow --
 *   never changes; the old approach of thinning the nodes did. */

import { createField, seededRandom, type Frame } from "./field";
import { createCanvas2DRenderer, type Renderer } from "./render-2d";
import { createWebGLRenderer } from "./render-gl";
import type { AnyCanvas } from "./sprite";

export type RendererChoice = "auto" | "webgl2" | "canvas2d";

export interface EngineOptions {
  width: number;
  height: number;
  dpr: number;
  reduceMotion: boolean;
  renderer?: RendererChoice;
  /** Tests: a seeded field, so two renderers can draw the same frame. */
  seed?: number;
  /** Tests: simulate this many ms at a fixed 60 fps step, draw once, and stop. */
  stillAfterMs?: number;
}

export interface Engine {
  rendererName: Renderer["name"];
  resize(width: number, height: number, dpr: number): void;
  pointer(x: number, y: number): void;
  setVisible(visible: boolean): void;
  stop(): void;
}

const SLOW_FRAME_MS = 24;
const GAP_WINDOW = 60;
const WARMUP_FRAMES = 150;
// A frame is drawn once at least (interval - slack) has passed, so on a 60 Hz
// display vsync jitter never makes it skip a frame it should draw.
const PACE_SLACK_MS = 3;
const REBUILD_DEBOUNCE_MS = 200;

function pickRenderer(canvas: AnyCanvas, choice: RendererChoice): Renderer | null {
  if (choice !== "canvas2d") {
    const gl = createWebGLRenderer(canvas);
    if (gl || choice === "webgl2") return gl;
  }
  // null if a WebGL context was already taken on this canvas -- the host
  // then retries on a fresh canvas with Canvas 2D forced
  return createCanvas2DRenderer(canvas);
}

type Schedule = (cb: (now: number) => void) => number;

export function startEngine(canvas: AnyCanvas, options: EngineOptions): Engine | null {
  const renderer = pickRenderer(canvas, options.renderer ?? "auto");
  if (!renderer) return null;

  const field = createField(options.seed != null ? seededRandom(options.seed) : Math.random);
  let width = options.width;
  let height = options.height;
  let dpr = options.dpr;
  const still = options.reduceMotion || options.stillAfterMs != null;
  renderer.resize(width, height, dpr);
  field.build(width, height);

  const pointer = { x: 0.5, y: 0.4, tx: 0.5, ty: 0.4 };
  const schedule: Schedule =
    typeof requestAnimationFrame === "function"
      ? (cb) => requestAnimationFrame(cb)
      : (cb) => setTimeout(() => cb(performance.now()), 16) as unknown as number;
  const cancel = (id: number) => (typeof cancelAnimationFrame === "function" ? cancelAnimationFrame(id) : clearTimeout(id));

  let handle = 0;
  let running = true;
  let visible = true;
  let lastRender = performance.now();
  let minInterval = 1000 / 60;
  let slowed = false;
  const gaps = new Float32Array(GAP_WINDOW);
  let gapCount = 0;
  let gapIdx = 0;
  let framesSinceBuild = 0;
  let rebuildTimer: ReturnType<typeof setTimeout> | null = null;

  function draw(frame: Frame) {
    renderer!.draw(frame);
  }

  function drawStill() {
    const simulate = options.stillAfterMs ?? 0;
    const stepMs = 1000 / 60;
    let t = 0;
    for (; t + stepMs <= simulate; t += stepMs) field.step(t, stepMs / 1000, pointer);
    draw(field.step(t, 0, pointer));
  }

  function tick(now: number) {
    handle = 0;
    if (!running || !visible) return;
    handle = schedule(tick);
    const gap = now - lastRender;
    if (gap < minInterval - PACE_SLACK_MS) return;
    lastRender = now;
    const dt = Math.min(gap / 1000, 0.05);

    // the parallax eases toward the pointer at the same rate at any frame rate
    const ease = 1 - Math.pow(0.98, dt * 60);
    pointer.x += (pointer.tx - pointer.x) * ease;
    pointer.y += (pointer.ty - pointer.y) * ease;
    draw(field.step(now, dt, pointer));

    // step down to ~30 fps if frames consistently arrive late; gaps over
    // 100ms are tab switches or throttling, not real cost
    if (gap > 0 && gap < 100) {
      gaps[gapIdx] = gap;
      gapIdx = (gapIdx + 1) % GAP_WINDOW;
      if (gapCount < GAP_WINDOW) gapCount++;
    }
    framesSinceBuild++;
    if (!slowed && framesSinceBuild > WARMUP_FRAMES && gapCount === GAP_WINDOW && framesSinceBuild % GAP_WINDOW === 0) {
      const sorted = Array.from(gaps).sort((a, b) => a - b);
      if (sorted[GAP_WINDOW >> 1] > SLOW_FRAME_MS) {
        slowed = true;
        minInterval = 1000 / 30;
      }
    }
  }

  function startLoop() {
    if (still || handle || !running || !visible) return;
    lastRender = performance.now();
    handle = schedule(tick);
  }

  if (still) drawStill();
  else startLoop();

  return {
    rendererName: renderer.name,
    resize(w, h, nextDpr) {
      width = w;
      height = h;
      dpr = nextDpr;
      renderer.resize(width, height, dpr);
      if (rebuildTimer) clearTimeout(rebuildTimer);
      rebuildTimer = setTimeout(() => {
        rebuildTimer = null;
        field.build(width, height);
        framesSinceBuild = 0;
        gapCount = 0;
        gapIdx = 0;
        if (still) drawStill();
      }, REBUILD_DEBOUNCE_MS);
      // resizing clears the canvas; keep a frame on screen meanwhile
      if (still) draw(field.step(performance.now(), 0, pointer));
    },
    pointer(x, y) {
      pointer.tx = x;
      pointer.ty = y;
    },
    setVisible(next) {
      visible = next;
      if (!visible && handle) {
        cancel(handle);
        handle = 0;
      } else if (visible) {
        startLoop();
      }
    },
    stop() {
      running = false;
      if (handle) cancel(handle);
      handle = 0;
      if (rebuildTimer) clearTimeout(rebuildTimer);
      renderer.dispose();
    },
  };
}
