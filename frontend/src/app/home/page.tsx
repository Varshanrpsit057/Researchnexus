"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ArrowRight, CheckCircle, CircleDashed, UploadSimple, Warning } from "@phosphor-icons/react/dist/ssr";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { papers as papersApi, workspaces as workspacesApi } from "@/lib/api/endpoints";
import { COVERAGE_LABEL } from "@/lib/coverage";
import { authorLine } from "@/lib/discovery-results";
import { nextStep } from "@/lib/library";
import { clearNewAccount, peekNewAccount } from "@/lib/recent-accounts";
import { parseTimestamp } from "@/lib/time";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { Reveal } from "@/components/effects/Reveal";
import { Timestamp } from "@/components/ui/Timestamp";
import { C, COVERAGE_TONE, focusRing, panel, primaryButton, quietButton } from "@/components/cinematic/ui";

const STEPS: { title: string; text: string }[] = [
  { title: "Upload a paper", text: "Its sections, abstract and references are read, and its record completed from the scholarly sources." },
  { title: "Analyse it", text: "A research profile: its problem, methods, datasets, results and limitations, each with the passage it comes from." },
  { title: "Discover related work", text: "Seven sources searched, every result ranked by criteria you weigh, with the reason for each rank." },
  { title: "Keep what matters in a workspace", text: "A research trail of typed connections, a graph through time, and chat that cites its passages." },
  { title: "Compare, find gaps, plan next steps", text: "A comparison table quoted from the papers, gaps two or more papers support, and directions from them." },
];

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

export default function HomePage() {
  const { ready } = useRequireAuth();
  const { me, signOut } = useAuth();
  // said once, right after sign-in made a new account
  const [newAccount] = useState(peekNewAccount);
  useEffect(() => clearNewAccount(), []);
  const wsQ = useSWR(ready ? "workspaces" : null, () => workspacesApi.list());
  const libraryQ = useSWR(ready ? "library" : null, () => papersApi.library());

  if (!ready) return null;

  const name = me?.email ? me.email.split("@")[0] : "researcher";
  const workspaces = [...(wsQ.data?.workspaces ?? [])].sort((a, b) => parseTimestamp(b.updated_at).getTime() - parseTimestamp(a.updated_at).getTime());
  const papers = libraryQ.data?.papers ?? [];
  const loaded = Boolean(wsQ.data && libraryQ.data);
  const fresh = loaded && workspaces.length === 0 && papers.length === 0;

  return (
    <PageShell>
      {newAccount && (
        <div
          role="status"
          className="mb-8 flex flex-wrap items-center justify-between gap-3 rounded-2xl px-5 py-4 text-[14px]"
          style={{ background: "rgba(93,240,168,.06)", border: "1px solid rgba(93,240,168,.3)" }}
        >
          <p className="max-w-[80ch] leading-relaxed">
            A new account was made for <span className="font-semibold">{newAccount}</span>. If your papers and workspaces are under another email,
            sign out and sign in with that one.
          </p>
          <button type="button" onClick={signOut} className={`rounded-full px-4 py-2 text-sm font-semibold hover:bg-white/10 ${focusRing}`} style={{ ...quietButton, color: C.ink }}>
            Sign out
          </button>
        </div>
      )}

      <Reveal>
        <h1 className="text-[clamp(28px,3.8vw,44px)] font-extrabold leading-[1.08] tracking-[-0.025em]">
          {fresh ? `Welcome, ${name}.` : `Welcome back, ${name}.`}
        </h1>
        <p className="mt-3 max-w-[62ch] text-[15.5px] leading-relaxed" style={{ color: C.muted }}>
          {fresh
            ? "Start from one paper you have, and ResearchNexus finds, ranks and connects the work around it, with the evidence for every step."
            : "Pick up where you left off, or start from a new paper."}
        </p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Link href="/papers" className={`inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
            <UploadSimple className="size-4" aria-hidden />
            Upload a paper
          </Link>
          {!fresh && (
            <>
              <Link href="/papers" className={`rounded-full px-5 py-2.5 text-sm font-semibold transition-colors hover:bg-white/10 ${focusRing}`} style={{ ...quietButton, color: C.ink }}>
                Your library
              </Link>
              <Link href="/workspaces" className={`rounded-full px-5 py-2.5 text-sm font-semibold transition-colors hover:bg-white/10 ${focusRing}`} style={{ ...quietButton, color: C.ink }}>
                All workspaces
              </Link>
            </>
          )}
        </div>
      </Reveal>

      {me && !me.has_working_llm_key && (
        <Reveal delay={0.05}>
          <div
            className="mt-8 flex flex-wrap items-center gap-3 rounded-2xl px-5 py-3.5 text-sm"
            style={{ background: "rgba(232,193,92,.07)", border: "1px solid rgba(232,193,92,.3)", color: C.warning }}
          >
            <Warning className="size-4 shrink-0" weight="bold" aria-hidden />
            <span className="min-w-0 flex-1">No working language model key is saved yet. Analysing papers needs one, and so do chat, comparison, gaps and directions.</span>
            <Link href="/settings#models" className={`shrink-0 rounded-sm font-semibold underline underline-offset-4 ${focusRing}`}>
              Add a key
            </Link>
          </div>
        </Reveal>
      )}

      {fresh ? (
        <Reveal delay={0.1}>
          <section aria-labelledby="how-heading" className="mt-14">
            <h2 id="how-heading" className="text-lg font-bold">
              How a review goes
            </h2>
            <ol className="mt-5 grid grid-cols-[minmax(0,1fr)] gap-px overflow-hidden rounded-2xl md:grid-cols-5" style={{ ...panel, background: C.line }}>
              {STEPS.map((s, i) => (
                <li key={s.title} className="px-5 py-5" style={{ background: "rgba(8,12,26,.92)" }}>
                  <span className="text-[13px] font-semibold tabular-nums" style={{ color: C.mint }}>
                    Step {i + 1}
                  </span>
                  <p className="mt-2 text-[15px] font-semibold leading-snug">{s.title}</p>
                  <p className="mt-1.5 text-[13px] leading-relaxed" style={{ color: C.muted }}>
                    {s.text}
                  </p>
                </li>
              ))}
            </ol>
          </section>
        </Reveal>
      ) : (
        <div className="mt-14 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-12">
          <Reveal delay={0.08}>
            <section aria-labelledby="ws-heading">
              <div className="flex items-baseline justify-between gap-3">
                <h2 id="ws-heading" className="text-lg font-bold">
                  Your workspaces
                </h2>
                {workspaces.length > 3 && (
                  <Link href="/workspaces" className={`inline-flex items-center gap-1 rounded-sm text-sm font-medium ${focusRing}`} style={{ color: C.mint }}>
                    All {workspaces.length} <ArrowRight className="size-3.5" aria-hidden />
                  </Link>
                )}
              </div>
              <div className="mt-4">
                {!wsQ.data ? (
                  <div role="status" className="h-40 rounded-2xl motion-safe:animate-pulse" style={panel}>
                    <span className="sr-only">Loading your workspaces…</span>
                  </div>
                ) : workspaces.length === 0 ? (
                  <p className="rounded-2xl px-5 py-8 text-center text-sm leading-relaxed" style={{ ...panel, border: `1px dashed ${C.lineStrong}`, color: C.muted }}>
                    No workspace yet. Analyse a paper, discover related work, then keep the results you want in one.
                  </p>
                ) : (
                  <ul className="overflow-hidden rounded-2xl" style={panel}>
                    {workspaces.slice(0, 3).map((ws) => (
                      <li key={ws.workspace_id} className="border-b last:border-b-0" style={{ borderColor: C.line }}>
                        <Link href={`/workspace/${ws.workspace_id}`} className={`group block px-5 py-4 transition-colors hover:bg-white/[0.03] ${focusRing}`}>
                          <span className="flex items-baseline justify-between gap-3">
                            <span className="text-[15.5px] font-semibold group-hover:text-white">{ws.title}</span>
                            <ArrowRight className="size-4 shrink-0 translate-y-0.5 opacity-60 transition-transform group-hover:translate-x-0.5" aria-hidden />
                          </span>
                          {ws.seed_title && (
                            <span className="mt-1 block truncate text-[13px]" style={{ color: C.muted }}>
                              From {ws.seed_title}
                            </span>
                          )}
                          <span className="mt-2 block text-[12.5px] tabular-nums" style={{ color: C.muted2 }}>
                            {plural(ws.counts?.papers ?? ws.papers.length, "paper")}
                            {ws.counts && ` · ${plural(ws.counts.edges, "connection")} · ${plural(ws.counts.gaps, "gap")}`} · updated <Timestamp at={ws.updated_at} />
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          </Reveal>

          <Reveal delay={0.12}>
            <section aria-labelledby="papers-heading">
              <div className="flex items-baseline justify-between gap-3">
                <h2 id="papers-heading" className="text-lg font-bold">
                  Recent papers
                </h2>
                {papers.length > 5 && (
                  <Link href="/papers" className={`inline-flex items-center gap-1 rounded-sm text-sm font-medium ${focusRing}`} style={{ color: C.mint }}>
                    All {papers.length} <ArrowRight className="size-3.5" aria-hidden />
                  </Link>
                )}
              </div>
              <div className="mt-4">
                {!libraryQ.data ? (
                  <div role="status" className="h-40 rounded-2xl motion-safe:animate-pulse" style={panel}>
                    <span className="sr-only">Loading your papers…</span>
                  </div>
                ) : papers.length === 0 ? (
                  <p className="rounded-2xl px-5 py-8 text-center text-sm" style={{ ...panel, border: `1px dashed ${C.lineStrong}`, color: C.muted }}>
                    Papers you upload, analyse or collect appear here.
                  </p>
                ) : (
                  <ul className="overflow-hidden rounded-2xl" style={panel}>
                    {papers.slice(0, 5).map((p) => {
                      const step = nextStep(p);
                      return (
                        <li key={p.id} className="flex items-start justify-between gap-4 border-b px-5 py-3.5 last:border-b-0" style={{ borderColor: C.line }}>
                          <div className="min-w-0">
                            <Link href={`/papers/${p.id}`} className={`line-clamp-2 rounded-sm text-[14px] font-semibold leading-snug hover:underline hover:underline-offset-4 ${focusRing}`}>
                              {p.title}
                            </Link>
                            <p className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[12.5px]" style={{ color: C.muted }}>
                              <span className="truncate">{[authorLine(p.authors), p.year].filter(Boolean).join(" · ")}</span>
                              <span className="inline-flex items-center gap-1">
                                <span className="size-1.5 rounded-full" style={{ background: COVERAGE_TONE[p.coverage.state] }} aria-hidden />
                                {COVERAGE_LABEL[p.coverage.state]}
                              </span>
                              {p.analyzed ? (
                                <span className="inline-flex items-center gap-1" style={{ color: C.mint }}>
                                  <CheckCircle className="size-3.5" weight="fill" aria-hidden />
                                  Profile
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1">
                                  <CircleDashed className="size-3.5" aria-hidden />
                                  Not analysed
                                </span>
                              )}
                            </p>
                          </div>
                          <Link
                            href={step.href}
                            className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-[12.5px] font-semibold transition-colors hover:bg-white/10 ${focusRing}`}
                            style={{ ...quietButton, color: C.ink }}
                          >
                            {step.label}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </section>
          </Reveal>
        </div>
      )}
    </PageShell>
  );
}
