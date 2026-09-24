"use client";

import { useEffect, useRef } from "react";
import type { Engine, EngineOptions, RendererChoice } from "./constellation/engine";
import { startEngine } from "./constellation/engine";
import type { FromWorker, ToWorker } from "./constellation/constellation.worker";

interface ConstellationProps {
  className?: string;
}

/** QA/test hook, read once at mount: force a renderer or thread, seed the
 * field, or draw one still frame -- used by the renderer-parity check. */
interface ConstellationDebug {
  renderer?: RendererChoice;
  thread?: "main" | "worker";
  seed?: number;
  stillAfterMs?: number;
}

interface Bridge {
  resize(width: number, height: number): void;
  pointer(x: number, y: number): void;
  visible(visible: boolean): void;
  stop(): void;
}

function makeCanvas(): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.style.display = "block";
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  return canvas;
}

/** The one shared, globally-mounted research-intelligence background --
 * mounted once in the root layout, never per-page, so it survives route
 * navigation without remounting. Fixed-position and viewport-sized, so it
 * reads identically at every scroll position.
 *
 * A dense computational network field: thousands of drifting nodes whose
 * links are recomputed every frame by distance, so connections continuously
 * form and dissolve as nodes move; a sparser curved backbone between larger
 * "major" nodes carries travelling activation pulses (see
 * constellation/field.ts).
 *
 * Built to stay light on low-end machines without looking any different:
 * - it runs in a Web Worker on an OffscreenCanvas where the browser allows,
 *   so none of its per-frame work lands on the UI thread;
 * - it draws with WebGL2 (five instanced draw calls a frame), falling back
 *   to Canvas 2D where WebGL2 is missing or would run in software;
 * - it draws at most ~60 fps, even on high-refresh displays, and steps down
 *   to ~30 fps rather than thinning the field when a device falls behind;
 * - it stops entirely while the tab is hidden.
 * Under prefers-reduced-motion it draws one still frame and never animates.
 * The active path is exposed as data-renderer / data-thread on the canvas. */
export default function Constellation({ className }: ConstellationProps) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const debug = (window as unknown as { __RN_CONSTELLATION__?: ConstellationDebug }).__RN_CONSTELLATION__ ?? {};
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const options: EngineOptions = {
      width: window.innerWidth,
      height: window.innerHeight,
      dpr,
      reduceMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      renderer: debug.renderer ?? "auto",
      seed: debug.seed,
      stillAfterMs: debug.stillAfterMs,
    };

    let canvas = makeCanvas();
    host.appendChild(canvas);
    let stopped = false;

    function mark(renderer: Engine["rendererName"], thread: "main" | "worker") {
      canvas.dataset.renderer = renderer;
      canvas.dataset.thread = thread;
    }

    function freshCanvas() {
      canvas.remove();
      canvas = makeCanvas();
      host!.appendChild(canvas);
    }

    function startOnMainThread(): Bridge | null {
      let engine = startEngine(canvas, options);
      if (!engine && options.renderer !== "canvas2d") {
        // a WebGL context was taken but unusable; Canvas 2D needs a new canvas
        freshCanvas();
        engine = startEngine(canvas, { ...options, renderer: "canvas2d" });
      }
      if (!engine) return null;
      mark(engine.rendererName, "main");
      const e = engine;
      return {
        resize: (w, h) => e.resize(w, h, dpr),
        pointer: (x, y) => e.pointer(x, y),
        visible: (v) => e.setVisible(v),
        stop: () => e.stop(),
      };
    }

    function startInWorker(): Bridge | null {
      if (debug.thread === "main" || typeof Worker === "undefined" || !("transferControlToOffscreen" in canvas)) return null;
      let worker: Worker;
      let offscreen: OffscreenCanvas;
      try {
        worker = new Worker(new URL("./constellation/constellation.worker.ts", import.meta.url), { type: "module" });
        offscreen = canvas.transferControlToOffscreen();
      } catch {
        return null;
      }
      const post = (msg: ToWorker, transfer: Transferable[] = []) => worker.postMessage(msg, transfer);
      let fallback: Bridge | null = null;
      const fallBack = () => {
        worker.terminate();
        if (stopped || fallback) return;
        freshCanvas();
        fallback = startOnMainThread();
      };
      worker.onmessage = (e: MessageEvent<FromWorker>) => {
        if (e.data.type === "ready") mark(e.data.renderer, "worker");
        else fallBack();
      };
      worker.onerror = (e) => {
        e.preventDefault();
        fallBack();
      };
      post({ type: "init", canvas: offscreen, options }, [offscreen]);
      return {
        resize: (w, h) => (fallback ? fallback.resize(w, h) : post({ type: "resize", width: w, height: h, dpr })),
        pointer: (x, y) => (fallback ? fallback.pointer(x, y) : post({ type: "pointer", x, y })),
        visible: (v) => (fallback ? fallback.visible(v) : post({ type: "visible", visible: v })),
        stop: () => {
          if (fallback) fallback.stop();
          else post({ type: "stop" });
          worker.terminate();
        },
      };
    }

    const bridge = startInWorker() ?? startOnMainThread();

    const onResize = () => bridge?.resize(window.innerWidth, window.innerHeight);
    const onPointer = (e: PointerEvent) => bridge?.pointer(e.clientX / window.innerWidth, e.clientY / window.innerHeight);
    const onVisibility = () => bridge?.visible(!document.hidden);
    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onPointer, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stopped = true;
      bridge?.stop();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", onVisibility);
      canvas.remove();
    };
  }, []);

  return <div ref={hostRef} className={className} aria-hidden />;
}
