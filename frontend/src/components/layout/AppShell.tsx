"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FlaskIcon, GearSix, SignOut, UploadSimple } from "@phosphor-icons/react/dist/ssr";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/Button";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, signOut, isAuthenticated, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace(`/sign-in?next=${encodeURIComponent(pathname)}`);
    }
  }, [isLoading, isAuthenticated, pathname, router]);

  if (!isLoading && !isAuthenticated) {
    return null;
  }

  return (
    // the neural background behind every page is dark: the light palette put dark titles on it
    <div data-theme="dark" className="relative flex min-h-dvh flex-col text-ink">
      {/* the same scrim the cinematic pages lay over the background, so dense content stays legible */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{ background: "linear-gradient(180deg, rgba(4,6,15,.55) 0%, rgba(4,6,15,.82) 320px, rgba(4,6,15,.9) 100%)" }}
      />
      <header className="border-b border-border-strong bg-surface-raised">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-4">
          <Link
            href="/papers"
            aria-label="ResearchNexus, home"
            className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
          >
            <FlaskIcon className="size-4.5 text-accent" weight="duotone" aria-hidden />
            <span className="hidden sm:inline">ResearchNexus</span>
          </Link>
          <nav aria-label="Primary" className="flex items-center gap-1">
            <Link
              href="/papers"
              aria-current={pathname.startsWith("/papers") ? "page" : undefined}
              className="rounded-sm px-2 py-1.5 text-sm font-medium text-ink-muted transition-colors hover:text-ink aria-[current=page]:text-ink sm:px-3"
            >
              Papers
            </Link>
            <Link
              href="/workspaces"
              aria-current={pathname.startsWith("/workspaces") ? "page" : undefined}
              className="rounded-sm px-2 py-1.5 text-sm font-medium text-ink-muted transition-colors hover:text-ink aria-[current=page]:text-ink sm:px-3"
            >
              Workspaces
            </Link>
            <Link href="/papers" aria-label="Upload paper" className="ml-1 sm:ml-2">
              <Button size="sm" variant="secondary">
                <UploadSimple className="size-4" aria-hidden />
                <span className="hidden sm:inline">Upload paper</span>
              </Button>
            </Link>
            <Link
              href="/settings"
              aria-label="LLM provider settings"
              className="ml-1 rounded-sm p-2 text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
            >
              <GearSix className="size-4.5" aria-hidden />
            </Link>
            {me && (
              <button
                type="button"
                onClick={signOut}
                aria-label={`Sign out of ${me.email}`}
                className="ml-1 rounded-sm p-2 text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
              >
                <SignOut className="size-4.5" aria-hidden />
              </button>
            )}
          </nav>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6">
        {children}
      </main>
    </div>
  );
}
