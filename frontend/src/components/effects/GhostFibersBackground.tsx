"use client";

import { useEffect, useRef, useState } from "react";
import GhostFibers from "./ghost-fibers/GhostFibers";
import { FIBERS_AT_REST, fibersDuringMorph, fibersReleasing, type FibersDynamics } from "./fibers-morph";
import { MORPH } from "./constellation/field";
import { onBackgroundCommand } from "@/lib/background-bus";

/** The React Bits GhostFibers component (unmodified, ./ghost-fibers), with the
 * configuration chosen for ResearchNexus (dpr 1, as in that configuration),
 * made laptop-safe: never drawn above 1x -- a 1.5x or 2x laptop screen still
 * gets 1x, a quarter of the pixels at 2x -- capped at 30 fps, four layers. It
 * pauses itself when the tab is hidden and under reduced motion. */
const CONFIG = {
  lineColor: "#28350e",
  glowColor: "#0f2d09",
  scale: 2,
  rotation: 0,
  rotationSpeed: 0.25,
  layers: 4,
  waveAmplitude: 0.015,
  waveFrequency: 3,
  waveSpeed: 0.15,
  layerSpeed: 0.08,
  twistFrequency: 5,
  twistSpeed: 1.2,
  lineFrequency: 5,
  lineSpacing: 2,
  lineSharpness: 16,
  glowFalloff: 10,
  blueBoost: 1.25,
  grain: 0.05,
  fps: 30,
} as const;
const FRAME_MS = 1000 / 30;

function laptopSafeDpr(): number {
  return Math.min(window.devicePixelRatio || 1, 1);
}

/** The no-dedicated-GPU background. It takes part in the graph transition
 * (fibers-morph.ts) instead of being swapped out: the same field speeds up,
 * draws in and dims while the graph emerges over it, then eases back. */
export default function GhostFibersBackground() {
  const [dyn, setDyn] = useState<FibersDynamics>(FIBERS_AT_REST);
  const [mode, setMode] = useState<"field" | "graph">("field");
  const [dpr] = useState(laptopSafeDpr);
  const current = useRef<FibersDynamics>(FIBERS_AT_REST);

  useEffect(() => {
    let frame = 0;
    let last = 0;
    const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const apply = (next: FibersDynamics) => {
      current.current = next; // where a release starts from
      setDyn(next);
    };
    const run = (at: (t: number) => FibersDynamics, until: number) => {
      cancelAnimationFrame(frame);
      if (reduced()) {
        apply(at(until)); // no animation: straight to where it would end
        return;
      }
      const t0 = performance.now();
      const tick = (now: number) => {
        const t = (now - t0) / 1000;
        if (now - last >= FRAME_MS || t >= until) {
          last = now;
          apply(at(Math.min(t, until)));
        }
        if (t < until) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    };
    const off = onBackgroundCommand((cmd) => {
      if (cmd.type === "morph") {
        setMode("graph");
        run(fibersDuringMorph, MORPH.energize[3] + 0.2);
      } else {
        setMode("field");
        const from = current.current;
        run((t) => fibersReleasing(from, t), MORPH.release);
      }
    });
    return () => {
      off();
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="h-full w-full overflow-hidden" data-effect="fibers" data-mode={mode} data-testid="ghost-fibers">
      <div className="h-full w-full" style={{ transform: `scale(${dyn.zoom})`, transformOrigin: "50% 50%" }}>
        <GhostFibers
          {...CONFIG}
          speed={dyn.speed}
          twist={dyn.twist}
          glowIntensity={dyn.glowIntensity}
          brightness={dyn.brightness}
          vignette={dyn.vignette}
          dpr={dpr}
        />
      </div>
    </div>
  );
}
