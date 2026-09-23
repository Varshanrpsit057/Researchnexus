"use client";

import Link from "next/link";
import { FlaskIcon, GearSix, SignOut, UploadSimple } from "@phosphor-icons/react/dist/ssr";
import { useAuth } from "@/lib/auth/auth-context";
import { CINEMATIC } from "@/lib/cinematic-theme";

/** The shared header for every authenticated cinematic page (home, seed
 * paper, and beyond) -- one implementation so the responsive collapse
 * (wordmark and "Upload paper" label hide below `sm:`, matching the real
 * AppShell's own tested pattern) and the real sign-out action stay
 * consistent instead of drifting per page. */
export function CinematicHeader() {
  const { signOut } = useAuth();
  return (
    <header className="relative border-b" style={{ borderColor: CINEMATIC.line }}>
      <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between gap-2 px-4 sm:px-6">
        <Link
          href="/home"
          aria-label="ResearchNexus, home"
          className="inline-flex shrink-0 items-center gap-2 text-sm font-extrabold tracking-[0.16em]"
        >
          <FlaskIcon className="size-[18px]" style={{ color: CINEMATIC.mint }} weight="duotone" aria-hidden />
          <span className="hidden sm:inline">RESEARCHNEXUS</span>
        </Link>
        <nav className="flex items-center gap-0.5 text-sm sm:gap-1" style={{ color: CINEMATIC.muted }}>
          <Link href="/papers" className="rounded-full px-2.5 py-1.5 transition-colors hover:text-white sm:px-3">
            Papers
          </Link>
          <Link href="/workspaces" className="rounded-full px-2.5 py-1.5 transition-colors hover:text-white sm:px-3">
            Workspaces
          </Link>
          <Link
            href="/papers"
            aria-label="Upload paper"
            className="ml-1 inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-semibold sm:ml-2 sm:px-4"
            style={{ color: CINEMATIC.mintInk, background: `linear-gradient(180deg, ${CINEMATIC.mint}, ${CINEMATIC.mint2})` }}
          >
            <UploadSimple className="size-4 shrink-0" aria-hidden />
            <span className="hidden sm:inline">Upload paper</span>
          </Link>
          <Link
            href="/settings"
            aria-label="Settings"
            className="ml-1 shrink-0 rounded-full p-2 transition-colors hover:text-white"
          >
            <GearSix className="size-[18px]" aria-hidden />
          </Link>
          <button
            type="button"
            onClick={signOut}
            aria-label="Sign out"
            className="shrink-0 rounded-full p-2 transition-colors hover:text-white"
            style={{ color: CINEMATIC.muted }}
          >
            <SignOut className="size-[18px]" aria-hidden />
          </button>
        </nav>
      </div>
    </header>
  );
}
