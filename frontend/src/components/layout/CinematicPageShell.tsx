"use client";

import type { ReactNode } from "react";
import { CinematicHeader } from "./CinematicHeader";
import { CINEMATIC } from "@/lib/cinematic-theme";

/** The shared shell for every authenticated cinematic page beyond home
 * (seed paper, discovery, and beyond): the header, a scrim over the global
 * constellation dense enough for real dense content to stay legible, and a
 * centered content column. One implementation so the scrim tuning and
 * container width stop drifting per page as more of these ship. */
export function CinematicPageShell({ children, maxWidthClassName = "max-w-[1180px]" }: { children: ReactNode; maxWidthClassName?: string }) {
  return (
    <div className="relative min-h-dvh" style={{ color: CINEMATIC.ink }}>
      <div
        className="pointer-events-none fixed inset-0 -z-10"
        style={{ background: "linear-gradient(180deg, rgba(4,6,15,.55) 0%, rgba(4,6,15,.82) 320px, rgba(4,6,15,.9) 100%)" }}
      />
      <CinematicHeader />
      <main id="main" className={`mx-auto px-4 py-10 sm:px-6 sm:py-14 ${maxWidthClassName}`}>
        {children}
      </main>
    </div>
  );
}
