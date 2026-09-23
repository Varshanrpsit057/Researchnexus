"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import useSWR from "swr";
import { motion, useReducedMotion, type Variants } from "motion/react";
import {
  ArrowRight,
  ChartBar,
  Columns,
  Compass,
  FileText,
  FlaskIcon,
  GearSix,
  GitBranch,
  Lightbulb,
  MagnifyingGlass,
  SignOut,
  UploadSimple,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import { useAuth } from "@/lib/auth/auth-context";
import { workspaces as workspacesApi } from "@/lib/api/endpoints";
import { useRecentPapers } from "@/lib/local-history";
import type { ComponentType } from "react";

// Same dark/mint world as landing and sign-in, carried one step into the
// authenticated app -- but calmer: no full WebGL constellation on a page
// whose job is to get a researcher back to real work, only its resting
// atmosphere. AppShell and the rest of the authenticated app deliberately
// keep the existing light/dark-adaptive "Index" tokens for now; extending
// this palette further is a separate, much larger decision this phase does
// not make on its own.
const INK = "#f3f6ff";
const MUTED = "#9aa6c4";
const MUTED_2 = "#6b7796";
const MINT = "#5df0a8";
const MINT_2 = "#2fd38a";
const MINT_INK = "#032018";
const GLASS = "rgba(12,18,38,.55)";
const LINE = "rgba(150,175,230,.12)";
const LINE_STRONG = "rgba(150,175,230,.22)";
const WARNING = "#e8c15c";

const fadeUp: Variants = { hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0 } };

function Reveal({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? "show" : "hidden"}
      animate="show"
      variants={fadeUp}
      transition={{ duration: reduce ? 0 : 0.5, delay: reduce ? 0 : delay, ease: [0.22, 0.7, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}

export default function HomePage() {
  const { me, isAuthenticated, isLoading, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace(`/sign-in?next=${encodeURIComponent(pathname)}`);
    }
  }, [isLoading, isAuthenticated, pathname, router]);

  const { data: wsData, isLoading: wsLoading } = useSWR(
    isAuthenticated ? "workspaces" : null,
    () => workspacesApi.list()
  );
  const recent = useRecentPapers();

  const list = wsData?.workspaces ?? [];
  const latestWorkspace = [...list].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  )[0];

  const { data: activityData, isLoading: activityLoading } = useSWR(
    latestWorkspace ? ["home-activity", latestWorkspace.workspace_id] : null,
    () => workspacesApi.activity(latestWorkspace!.workspace_id, { limit: 5 })
  );

  if (!isLoading && !isAuthenticated) return null;

  const firstName = me?.email ? me.email.split("@")[0] : "researcher";
  const wsHref = (suffix: string) => (latestWorkspace ? `/workspaces/${latestWorkspace.workspace_id}/${suffix}` : "/workspaces");

  const PIPELINE: { label: string; desc: string; icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>; href: string }[] = [
    { label: "Discover", desc: "Search arXiv, OpenAlex, Semantic Scholar, and Crossref.", icon: MagnifyingGlass, href: "/papers" },
    { label: "Understand", desc: "Extracted profiles, evidence spans, grounded chat.", icon: FileText, href: "/papers" },
    { label: "Rank", desc: "Transparent, per-signal explained scores.", icon: ChartBar, href: "/papers" },
    { label: "Connect", desc: "Typed relationships and the research graph.", icon: GitBranch, href: wsHref("trail") },
    { label: "Compare", desc: "Evidence-backed comparison across papers.", icon: Columns, href: wsHref("compare") },
    { label: "Find gaps", desc: "Evidence-grounded gaps awaiting review.", icon: Lightbulb, href: wsHref("gaps") },
    { label: "Develop directions", desc: "Turn an accepted gap into a direction.", icon: Compass, href: wsHref("directions") },
  ];

  return (
    <div className="relative min-h-dvh" style={{ color: INK }}>
      {/* A denser scrim than landing/sign-in: this page's job is to get a
          researcher back to real, dense work content (workspace cards,
          real numbers), so the shared constellation reads as ambient
          texture behind it rather than the immersive foreground it is on
          the arrival pages. */}
      <div
        className="pointer-events-none fixed inset-0 -z-10"
        style={{ background: "linear-gradient(180deg, rgba(4,6,15,.55) 0%, rgba(4,6,15,.82) 320px, rgba(4,6,15,.9) 100%)" }}
      />
      <header className="relative border-b" style={{ borderColor: LINE }}>
        <div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between gap-2 px-4 sm:px-6">
          <Link
            href="/home"
            aria-label="ResearchNexus, home"
            className="inline-flex shrink-0 items-center gap-2 text-sm font-extrabold tracking-[0.16em]"
          >
            <FlaskIcon className="size-[18px]" style={{ color: MINT }} weight="duotone" aria-hidden />
            <span className="hidden sm:inline">RESEARCHNEXUS</span>
          </Link>
          <nav className="flex items-center gap-0.5 text-sm sm:gap-1" style={{ color: MUTED }}>
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
              style={{ color: MINT_INK, background: `linear-gradient(180deg, ${MINT}, ${MINT_2})` }}
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
              style={{ color: MUTED }}
            >
              <SignOut className="size-[18px]" aria-hidden />
            </button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1180px] px-6 py-14">
        <Reveal>
          <h1 className="text-[clamp(26px,3.4vw,38px)] font-extrabold tracking-[-0.02em]">
            Welcome back, {firstName}.
          </h1>
          <p className="mt-2 text-[15.5px]" style={{ color: MUTED }}>
            Pick up a workspace, or start a new seed paper through discovery.
          </p>
        </Reveal>

        {!isLoading && me && !me.has_working_llm_key && (
          <Reveal delay={0.06}>
            <div
              className="mt-6 flex items-center gap-3 rounded-2xl px-5 py-3.5 text-sm"
              style={{ background: "rgba(232,193,92,.08)", border: "1px solid rgba(232,193,92,.25)", color: WARNING }}
            >
              <Warning className="size-4 shrink-0" weight="bold" aria-hidden />
              No working LLM provider key is saved yet. Analysis, discovery, chat, gaps, and directions need one.
              <Link href="/settings" className="ml-auto shrink-0 font-semibold underline underline-offset-2">
                Add a key
              </Link>
            </div>
          </Reveal>
        )}

        <Reveal delay={0.08}>
          <h2 className="mt-10 text-sm font-semibold uppercase tracking-wider" style={{ color: MUTED_2 }}>
            The research workflow
          </h2>
        </Reveal>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {PIPELINE.map((stage, i) => (
            <Reveal key={stage.label} delay={0.1 + i * 0.05}>
              <Link
                href={stage.href}
                className="group flex h-full flex-col gap-2.5 rounded-2xl p-4 transition-colors duration-200 hover:border-white/20"
                style={{ background: GLASS, border: `1px solid ${LINE}` }}
              >
                <span
                  className="inline-flex size-9 items-center justify-center rounded-xl"
                  style={{ background: "rgba(93,240,168,.1)", border: "1px solid rgba(93,240,168,.18)", color: MINT }}
                >
                  <stage.icon className="size-4" aria-hidden />
                </span>
                <span className="text-sm font-semibold">{stage.label}</span>
                <span className="text-xs leading-relaxed" style={{ color: MUTED }}>
                  {stage.desc}
                </span>
              </Link>
            </Reveal>
          ))}
        </div>

        <Reveal delay={0.1}>
          <div className="mt-12 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider" style={{ color: MUTED_2 }}>
              Your workspaces
            </h2>
            <Link href="/workspaces" className="inline-flex items-center gap-1 text-sm font-medium" style={{ color: MINT }}>
              View all <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </div>
        </Reveal>

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {wsLoading &&
            [0, 1, 2].map((i) => (
              <div key={i} className="h-28 animate-pulse rounded-2xl" style={{ background: GLASS, border: `1px solid ${LINE}` }} />
            ))}
          {!wsLoading && list.length === 0 && (
            <Reveal delay={0.14}>
              <div
                className="rounded-2xl px-6 py-10 text-center sm:col-span-2 lg:col-span-3"
                style={{ background: GLASS, border: `1px dashed ${LINE_STRONG}` }}
              >
                <p className="text-sm font-medium">No workspaces yet</p>
                <p className="mt-1.5 text-sm" style={{ color: MUTED }}>
                  Upload a seed paper, run discovery, then build a workspace from the results you accept.
                </p>
                <Link
                  href="/papers"
                  className="mt-4 inline-flex items-center gap-1.5 rounded-full px-5 py-2.5 text-sm font-semibold"
                  style={{ color: MINT_INK, background: `linear-gradient(180deg, ${MINT}, ${MINT_2})` }}
                >
                  Start from a seed paper <ArrowRight className="size-4" aria-hidden />
                </Link>
              </div>
            </Reveal>
          )}
          {!wsLoading &&
            list.map((ws, i) => (
              <Reveal key={ws.workspace_id} delay={0.1 + i * 0.06}>
                <Link
                  href={`/workspaces/${ws.workspace_id}`}
                  className="block h-full rounded-2xl p-5 transition-colors duration-200 hover:border-white/20"
                  style={{ background: GLASS, border: `1px solid ${LINE}` }}
                >
                  <p className="truncate text-sm font-semibold">{ws.title}</p>
                  <p className="mt-1 font-mono text-xs" style={{ color: MUTED_2 }}>
                    {ws.workspace_id}
                  </p>
                  <div className="mt-4 flex items-center justify-between text-xs" style={{ color: MUTED }}>
                    <span>{ws.papers.length} paper{ws.papers.length === 1 ? "" : "s"}</span>
                    <span>
                      ${ws.cost_used_usd.toFixed(2)} / ${ws.token_budget_usd.toFixed(2)}
                    </span>
                  </div>
                </Link>
              </Reveal>
            ))}
        </div>

        {latestWorkspace && (
          <>
            <Reveal delay={0.16}>
              <h2 className="mt-12 text-sm font-semibold uppercase tracking-wider" style={{ color: MUTED_2 }}>
                Recent activity · {latestWorkspace.title}
              </h2>
            </Reveal>
            <div className="mt-4">
              {activityLoading && (
                <div className="h-32 animate-pulse rounded-2xl" style={{ background: GLASS, border: `1px solid ${LINE}` }} />
              )}
              {!activityLoading && (!activityData || activityData.stage_runs.length === 0) && (
                <Reveal delay={0.2}>
                  <p
                    className="rounded-2xl px-6 py-8 text-center text-sm"
                    style={{ background: GLASS, border: `1px dashed ${LINE_STRONG}`, color: MUTED }}
                  >
                    No activity recorded yet in this workspace.
                  </p>
                </Reveal>
              )}
              {!activityLoading && activityData && activityData.stage_runs.length > 0 && (
                <Reveal delay={0.2}>
                  <div className="overflow-hidden rounded-2xl" style={{ background: GLASS, border: `1px solid ${LINE}` }}>
                    <ul className="divide-y" style={{ borderColor: LINE }}>
                      {activityData.stage_runs.map((run) => (
                        <li key={run.id} style={{ borderColor: LINE }}>
                          <div className="flex items-center gap-3 px-5 py-3">
                            <span
                              className="size-1.5 shrink-0 rounded-full"
                              style={{ background: run.ok ? MINT : "#ff9b9b" }}
                              aria-hidden
                            />
                            <span className="min-w-0 flex-1 truncate text-sm capitalize">{run.stage}</span>
                            <span className="shrink-0 font-mono text-xs" style={{ color: MUTED_2 }}>
                              {run.ok ? "ok" : "failed"} · {new Date(run.ts).toLocaleString()}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                </Reveal>
              )}
            </div>
          </>
        )}

        <Reveal delay={0.16}>
          <h2 className="mt-12 text-sm font-semibold uppercase tracking-wider" style={{ color: MUTED_2 }}>
            Recently uploaded in this browser
          </h2>
        </Reveal>
        <div className="mt-4">
          {recent.length === 0 ? (
            <Reveal delay={0.2}>
              <p
                className="rounded-2xl px-6 py-8 text-center text-sm"
                style={{ background: GLASS, border: `1px dashed ${LINE_STRONG}`, color: MUTED }}
              >
                Papers you upload will appear here for quick access.
              </p>
            </Reveal>
          ) : (
            <Reveal delay={0.2}>
              <div className="overflow-hidden rounded-2xl" style={{ background: GLASS, border: `1px solid ${LINE}` }}>
                <ul className="divide-y" style={{ borderColor: LINE }}>
                  {recent.map((p) => (
                    <li key={p.paperId} style={{ borderColor: LINE }}>
                      <Link
                        href={`/seed/${p.paperId}`}
                        className="flex items-center gap-3 px-5 py-3.5 text-sm transition-colors hover:bg-white/[0.03]"
                      >
                        <span className="min-w-0 flex-1 truncate">{p.title}</span>
                        <span className="shrink-0 font-mono text-xs" style={{ color: MUTED_2 }}>
                          {p.paperId}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            </Reveal>
          )}
        </div>
      </main>
    </div>
  );
}
