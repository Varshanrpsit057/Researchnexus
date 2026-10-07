"use client";

import { useEffect, useState } from "react";
import { MORPH } from "./constellation/field";
import { onBackgroundCommand } from "@/lib/background-bus";

/** The still background: no canvas, no animation loop, no GPU work -- the
 * dark ground, two soft glows in the ResearchNexus greens and a faint
 * lattice of points, all CSS. Behind the graph it simply fades to a dimmer
 * level (timed with MORPH.fade) and back when the graph is left. */
export default function StaticBackground() {
  const [mode, setMode] = useState<"field" | "graph">("field");
  useEffect(() => onBackgroundCommand((cmd) => setMode(cmd.type === "morph" ? "graph" : "field")), []);
  const graph = mode === "graph";
  return (
    <div
      className="h-full w-full"
      data-effect="static"
      data-mode={mode}
      data-testid="static-background"
      style={{
        background: [
          "radial-gradient(ellipse 70% 55% at 22% 28%, rgba(47,211,138,.10), transparent 70%)",
          "radial-gradient(ellipse 60% 50% at 78% 72%, rgba(40,53,14,.32), transparent 70%)",
          "radial-gradient(circle at 1px 1px, rgba(150,175,230,.10) 1px, transparent 1.5px) 0 0 / 28px 28px",
          "#04060f",
        ].join(", "),
        opacity: graph ? 0.55 : 1,
        transition: graph
          ? `opacity ${MORPH.fade[1] - MORPH.fade[0]}s ease ${MORPH.fade[0]}s`
          : `opacity ${MORPH.release}s ease`,
      }}
    />
  );
}
