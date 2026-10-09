"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FlaskIcon, GearSix, SignOut, UploadSimple } from "@phosphor-icons/react/dist/ssr";
import { useAuth } from "@/lib/auth/auth-context";
import { CINEMATIC } from "@/lib/cinematic-theme";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5df0a8]";

/** Which part of the app a path belongs to: a paper's pages under Papers, a
 * workspace's under Workspaces. */
function section(pathname: string): "papers" | "workspaces" | "settings" | null {
  if (/^\/(papers|seed|discover)(\/|$)/.test(pathname)) return "papers";
  if (/^\/(workspaces?|compare)(\/|$)/.test(pathname)) return "workspaces";
  if (pathname.startsWith("/settings")) return "settings";
  return null;
}

/** The shared header for every authenticated page -- one implementation so
 * the responsive collapse (wordmark and "Upload paper" label hide below
 * `sm:`), the current section and the sign-out action stay consistent. */
export function CinematicHeader() {
  const { signOut, me } = useAuth();
  const router = useRouter();
  const current = section(usePathname() ?? "");
  const who = me?.name || me?.email;
  const navLink = (key: "papers" | "workspaces", href: string, label: string) => {
    const on = current === key;
    return (
      <Link
        href={href}
        aria-current={on ? "page" : undefined}
        className={`relative rounded-full px-2.5 py-1.5 transition-colors hover:text-white sm:px-3 ${FOCUS}`}
        style={on ? { color: CINEMATIC.ink } : undefined}
      >
        {label}
        {on && (
          <span aria-hidden className="absolute inset-x-3 -bottom-[13px] h-[2px] rounded-full sm:inset-x-3.5" style={{ background: CINEMATIC.mint }} />
        )}
      </Link>
    );
  };
  return (
    <header className="relative border-b" style={{ borderColor: CINEMATIC.line }}>
      <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between gap-2 px-4 sm:px-6">
        <Link
          href="/home"
          aria-label="ResearchNexus, home"
          className={`inline-flex shrink-0 items-center gap-2 rounded-sm text-sm font-extrabold tracking-[0.16em] ${FOCUS}`}
        >
          <FlaskIcon className="size-[18px]" style={{ color: CINEMATIC.mint }} weight="duotone" aria-hidden />
          <span className="hidden sm:inline">RESEARCHNEXUS</span>
        </Link>
        <nav aria-label="Main" className="flex items-center gap-0.5 text-sm sm:gap-1" style={{ color: CINEMATIC.muted }}>
          {navLink("papers", "/papers", "Papers")}
          {navLink("workspaces", "/workspaces", "Workspaces")}
          <Link
            href="/papers"
            aria-label="Upload paper"
            className={`ml-1 inline-flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-semibold transition-[filter] hover:brightness-110 sm:ml-2 sm:px-4 ${FOCUS}`}
            style={{ color: CINEMATIC.mintInk, background: `linear-gradient(180deg, ${CINEMATIC.mint}, ${CINEMATIC.mint2})` }}
          >
            <UploadSimple className="size-4 shrink-0" aria-hidden />
            <span className="hidden sm:inline">Upload paper</span>
          </Link>
          <Link
            href="/settings"
            aria-label="Settings"
            aria-current={current === "settings" ? "page" : undefined}
            className={`ml-1 shrink-0 rounded-full p-2 transition-colors hover:text-white ${FOCUS}`}
            style={current === "settings" ? { color: CINEMATIC.mint } : undefined}
          >
            <GearSix className="size-[18px]" weight={current === "settings" ? "fill" : "regular"} aria-hidden />
          </Link>
          <button
            type="button"
            onClick={async () => {
              await signOut();
              router.replace("/sign-in");
            }}
            aria-label={who ? `Sign out (${who})` : "Sign out"}
            title={who ? `Signed in as ${who}. Sign out` : "Sign out"}
            className={`shrink-0 rounded-full p-2 transition-colors hover:text-white ${FOCUS}`}
            style={{ color: CINEMATIC.muted }}
          >
            <SignOut className="size-[18px]" aria-hidden />
          </button>
        </nav>
      </div>
    </header>
  );
}
