"use client";

import { useSyncExternalStore } from "react";

const WIDE = "(min-width: 1024px)";

/** Wide screens show a detail beside its list; narrow ones open it as a sheet. */
export function useIsWide(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const m = window.matchMedia(WIDE);
      m.addEventListener("change", onChange);
      return () => m.removeEventListener("change", onChange);
    },
    () => window.matchMedia(WIDE).matches,
    () => true,
  );
}
