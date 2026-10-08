"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Constellation from "./Constellation";
import StaticBackground from "./StaticBackground";
import { useBackground } from "@/lib/background-mode";
import { onBackgroundCommand } from "@/lib/background-bus";

// only loaded where it is used: a machine on the neural network never fetches it
const GhostFibersBackground = dynamic(() => import("./GhostFibersBackground"), { ssr: false });

/** The one background, mounted once in the root layout: exactly one effect
 * at a time -- the neural network, GhostFibers or a still ground -- chosen by
 * lib/background-mode.ts (Auto from the graphics in use, or the user's
 * choice), and switched in place when the setting changes. Until the browser
 * is known only the dark ground is drawn. Exposes what it chose for tests and
 * diagnostics: data-effect, data-tier, data-quality (the fibers' lighter
 * setting on a weak GPU), data-mode ("graph" while a page holds it in the
 * graph transition). */
export default function BackgroundHost() {
  const bg = useBackground();
  const [mode, setMode] = useState<"field" | "graph">("field");
  useEffect(() => onBackgroundCommand((cmd) => setMode(cmd.type === "morph" ? "graph" : "field")), []);

  return (
    <div
      className="h-full w-full"
      data-testid="background"
      data-effect={bg?.effect ?? "pending"}
      data-tier={bg?.tier ?? "pending"}
      data-choice={bg?.choice ?? "pending"}
      data-quality={bg ? (bg.light ? "light" : "full") : "pending"}
      data-mode={mode}
    >
      {bg?.effect === "neural" && <Constellation className="h-full w-full" />}
      {bg?.effect === "fibers" && <GhostFibersBackground light={bg.light} />}
      {bg?.effect === "static" && <StaticBackground />}
    </div>
  );
}
