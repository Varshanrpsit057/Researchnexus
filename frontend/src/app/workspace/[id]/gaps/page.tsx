"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import {
  ArrowCounterClockwise,
  ArrowLeft,
  ArrowRight,
  ChatCircleText,
  Check,
  GitBranch,
  Graph,
  MagnifyingGlass,
  Table,
  Warning,
  X,
} from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { papers as papersApi, workspaces } from "@/lib/api/endpoints";
import { useJobPolling } from "@/lib/api/hooks";
import type { Confidence, GapType, GapUserState, ResearchGap } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { Timestamp } from "@/components/ui/Timestamp";
import { useIsWide } from "@/lib/use-is-wide";
import {
  CONFIDENCE_LABEL,
  GAP_TYPE_LABEL,
  NO_FILTERS,
  RUN_STEPS,
  STATE_LABEL,
  countByState,
  filterGaps,
  runFailure,
  runOutcome,
  runProgress,
  sortGaps,
  type GapFilters,
  type RunProgress,
} from "@/lib/gaps";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { type PaperKind } from "../compare/parts";
import { C, InlineError, WorkspaceLoadError, focusRing, panel, primaryButton, quietButton } from "../ui";
import { DecisionButton, GapDetail, GapRow, StateMark } from "./parts";

// a run keeps going when the reader leaves the page; coming back picks it up again
const runKey = (workspaceId: string) => `researchnexus.gapsRun.${workspaceId}`;

function savedRun(workspaceId: string): string | null {
  try {
    return window.sessionStorage.getItem(runKey(workspaceId));
  } catch {
    return null;
  }
}

function saveRun(workspaceId: string, jobId: string | null): void {
  try {
    if (jobId) window.sessionStorage.setItem(runKey(workspaceId), jobId);
    else window.sessionStorage.removeItem(runKey(workspaceId));
  } catch {
    // storage blocked: the run still finishes, this tab just won't resume it
  }
}

async function profileGrounding(paperId: string): Promise<string | null> {
  try {
    return (await papersApi.getProfile(paperId)).grounding;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export default function GapsPage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const { me } = useAuth();
  const router = useRouter();
  const selectedId = useSearchParams().get("gap");
  const { mutate: mutateGlobal } = useSWRConfig();
  const isWide = useIsWide();

  const workspaceQ = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));
  // shared with the overview's gaps station
  const gapsQ = useSWR(ready && workspaceQ.data ? ["ws-gaps", id] : null, () => workspaces.listGaps(id));

  const workspace = workspaceQ.data;
  const gaps = useMemo(() => gapsQ.data?.gaps ?? [], [gapsQ.data]);
  const members = useMemo(() => workspace?.papers.map((p) => p.paper_id) ?? [], [workspace]);

  // every paper the gaps or the workspace name, fetched once; the per-paper cache fills from it
  const paperIds = useMemo(() => [...new Set([...members, ...gaps.flatMap((g) => g.supporting_papers)])].sort(), [members, gaps]);
  const titlesQ = useSWR(paperIds.length ? ["ws-paper-titles", ...paperIds] : null, async () => {
    const found = await Promise.all(paperIds.map((pid) => papersApi.get(pid).catch(() => null)));
    const titles: Record<string, string> = {};
    for (const p of found) {
      if (!p) continue;
      titles[p.id] = p.title;
      void mutateGlobal(["paper", p.id], p, { revalidate: false });
    }
    return titles;
  });
  const profilesQ = useSWR(ready && members.length ? ["ws-profiles", ...members] : null, async () =>
    Object.fromEntries(await Promise.all(members.map(async (pid) => [pid, await profileGrounding(pid)] as const))),
  );

  const [filters, setFilters] = useState<GapFilters>(NO_FILTERS);
  const [jobId, setJobId] = useState<string | null>(() => (typeof window === "undefined" ? null : savedRun(id)));
  const [runError, setRunError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const polling = useJobPolling(jobId);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [decideError, setDecideError] = useState<{ gapId: string; message: string } | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const focusOnOpen = useRef(false);
  const settledJob = useRef<string | null>(null);
  const mutateGaps = gapsQ.mutate;

  const running = starting || (jobId != null && !polling.isDone);
  const noKey = me != null && !me.has_working_llm_key;
  const outcome = polling.job?.status === "succeeded" ? runOutcome(polling.job.progress) : null;
  const failure = polling.job?.status === "failed" ? runFailure(polling.job.error, polling.job.progress) : null;
  const progress = runProgress(polling.job?.progress);
  const mutateProfiles = profilesQ.mutate;

  // a finished run changes the list, the papers' profiles and the overview's counts, once per run
  useEffect(() => {
    if (polling.isDone && jobId && settledJob.current !== jobId) {
      settledJob.current = jobId;
      saveRun(id, null);
      void mutateGaps();
      void mutateProfiles();
      void mutateGlobal(["workspace", id]);
    }
  }, [polling.isDone, jobId, mutateGaps, mutateProfiles, mutateGlobal, id]);

  const counts = countByState(gaps);
  const titles = titlesQ.data ?? {};
  const shown = filterGaps(gaps, filters, titles);
  const selected = selectedId ? (gaps.find((g) => g.gap_id === selectedId) ?? null) : null;
  // wide screens always show a gap: the chosen one, else the strongest shown
  const detail = selected ?? (isWide && !selectedId ? (shown[0] ?? null) : null);
  const toReview = sortGaps(gaps.filter((g) => g.user_state === "candidate"));
  const nextToReview = detail ? (toReview.find((g) => g.gap_id !== detail.gap_id) ?? null) : null;
  const typesPresent = [...new Set(gaps.map((g) => g.gap_type))].sort() as GapType[];
  const bandsPresent = (["high", "medium", "low"] as Confidence[]).filter((b) => gaps.some((g) => g.confidence === b));
  const paperCount = new Set(gaps.flatMap((g) => g.supporting_papers)).size;

  const kindOf = (paperId: string): PaperKind =>
    paperId === workspace?.seed_paper_id ? "seed" : members.includes(paperId) ? "member" : "connected";

  function select(gapId: string | null, fromUser = true) {
    if (gapId && fromUser && !isWide) {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      focusOnOpen.current = true;
    }
    router.replace(gapId ? `/workspace/${id}/gaps?gap=${encodeURIComponent(gapId)}` : `/workspace/${id}/gaps`, { scroll: false });
  }

  function closeSheet() {
    select(null, false);
    const back = returnFocus.current;
    returnFocus.current = null;
    if (back) requestAnimationFrame(() => back.focus());
  }

  // the sheet takes focus when a reader opens it, and Escape closes it
  const sheetOpen = !isWide && detail != null;
  const openGap = detail?.gap_id;
  useEffect(() => {
    if (focusOnOpen.current && sheetOpen) {
      focusOnOpen.current = false;
      headingRef.current?.focus();
    }
  }, [sheetOpen, openGap]);
  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeSheet();
    const root = document.documentElement;
    const before = root.style.overflow;
    root.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      root.style.overflow = before;
      window.removeEventListener("keydown", onKey);
    };
  });

  async function run() {
    if (running) return;
    setStarting(true);
    setRunError(null);
    setAnnouncement("Looking for gaps.");
    try {
      const res = await workspaces.generateGaps(id, {});
      saveRun(id, res.job.job_id);
      setJobId(res.job.job_id);
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      setRunError(
        err?.code === "llm_key_required"
          ? "No working LLM provider key is saved. Add one in Settings to look for gaps."
          : err
            ? "The run couldn't start. Try again in a moment."
            : "The server couldn't be reached. Check the connection and try again.",
      );
      setAnnouncement("The run couldn't start.");
    } finally {
      setStarting(false);
    }
  }

  async function decide(gap: ResearchGap, state: GapUserState) {
    setDeciding(gap.gap_id);
    setDecideError(null);
    const key = ["ws-gaps", id];
    const swap = (to: ResearchGap) => (data: { gaps: ResearchGap[] } | undefined) =>
      data ? { gaps: data.gaps.map((g) => (g.gap_id === to.gap_id ? to : g)) } : data;
    // keep this gap on screen after it leaves the filter it was found under
    if (selectedId !== gap.gap_id) select(gap.gap_id, false);
    await mutateGlobal(key, swap({ ...gap, user_state: state }), { revalidate: false });
    try {
      const saved = await workspaces.setGapState(id, gap.gap_id, state);
      await mutateGlobal(key, swap(saved), { revalidate: false });
      void mutateGlobal(["workspace", id]);
      setAnnouncement(state === "candidate" ? "Moved back to review." : `Gap ${state}.`);
    } catch {
      await mutateGlobal(key, swap(gap), { revalidate: false });
      setDecideError({ gapId: gap.gap_id, message: "That decision wasn't saved. Try again." });
      setAnnouncement("That decision wasn't saved.");
    } finally {
      setDeciding(null);
    }
  }

  if (!ready) return null;
  if (workspaceQ.error) {
    return (
      <PageShell>
        <WorkspaceLoadError error={workspaceQ.error} onRetry={() => workspaceQ.mutate()} />
      </PageShell>
    );
  }

  const detailActions = (gap: ResearchGap) => (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        {gap.user_state === "candidate" ? (
          <>
            <DecisionButton primary onClick={() => decide(gap, "accepted")} disabled={deciding != null}>
              <Check className="size-4" weight="bold" aria-hidden />
              Accept gap
            </DecisionButton>
            <DecisionButton onClick={() => decide(gap, "rejected")} disabled={deciding != null}>
              <X className="size-4" weight="bold" aria-hidden />
              Reject
            </DecisionButton>
          </>
        ) : (
          <>
            <span className="mr-1 text-sm font-semibold">
              <StateMark state={gap.user_state} />
            </span>
            <DecisionButton onClick={() => decide(gap, "candidate")} disabled={deciding != null}>
              <ArrowCounterClockwise className="size-4" aria-hidden />
              Move back to review
            </DecisionButton>
            {gap.user_state === "accepted" && (
              <Link
                href={`/workspace/${id}/directions?gap=${encodeURIComponent(gap.gap_id)}`}
                className={`inline-flex min-h-11 items-center rounded-full px-4 text-sm font-semibold transition-colors hover:bg-white/10 sm:min-h-9 ${focusRing}`}
                style={quietButton}
              >
                Propose directions
              </Link>
            )}
          </>
        )}
        {gap.user_state !== "candidate" && nextToReview && (
          <button
            type="button"
            onClick={() => select(nextToReview.gap_id)}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm px-1 text-sm font-semibold hover:text-white sm:ml-auto sm:min-h-9 ${focusRing}`}
            style={{ color: C.mint }}
          >
            Next to review
            <ArrowRight className="size-4" aria-hidden />
          </button>
        )}
      </div>
      {decideError?.gapId === gap.gap_id && (
        <div className="mt-2">
          <InlineError message={decideError.message} />
        </div>
      )}
      <nav aria-label="This gap's papers elsewhere" className="mt-2.5 flex flex-wrap gap-x-4 text-[13px]" style={{ color: C.muted }}>
        <NavLink href={`/workspace/${id}/compare`} icon={<Table className="size-3.5" aria-hidden />}>
          Compare the papers
        </NavLink>
        <NavLink href={`/workspace/${id}/trail`} icon={<GitBranch className="size-3.5" aria-hidden />}>
          Trail
        </NavLink>
        <NavLink href={`/workspace/${id}/graph`} icon={<Graph className="size-3.5" aria-hidden />}>
          Graph
        </NavLink>
      </nav>
    </div>
  );

  const detailFor = (gap: ResearchGap) => (
    <GapDetail
      ref={headingRef}
      gap={gap}
      workspaceId={id}
      kindOf={kindOf}
      generated={<Timestamp at={gap.generated_at} />}
      actions={detailActions(gap)}
    />
  );

  return (
    <PageShell maxWidthClassName="max-w-[1320px]">
      <div className="selection:bg-[rgba(93,240,168,0.28)] selection:text-white">
        <header className="border-b pb-6" style={{ borderColor: C.lineStrong }}>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            {workspace ? (
              <Link
                href={`/workspace/${id}`}
                className={`inline-flex min-h-11 min-w-0 items-center gap-1.5 rounded-sm text-sm hover:text-white sm:min-h-0 ${focusRing}`}
                style={{ color: C.muted }}
              >
                <ArrowLeft className="size-4 shrink-0" aria-hidden />
                <span className="truncate">{workspace.title}</span>
              </Link>
            ) : (
              <div className="h-5 w-48 rounded motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.08)" }} />
            )}
            <nav aria-label="Related views" className="flex flex-wrap items-center gap-x-4 text-sm sm:ml-auto" style={{ color: C.muted }}>
              <NavLink href={`/workspace/${id}/trail`} icon={<GitBranch className="size-4" aria-hidden />}>
                Trail
              </NavLink>
              <NavLink href={`/workspace/${id}/graph`} icon={<Graph className="size-4" aria-hidden />}>
                Graph
              </NavLink>
              <NavLink href={`/workspace/${id}/compare`} icon={<Table className="size-4" aria-hidden />}>
                Compare
              </NavLink>
              <NavLink href={`/workspace/${id}/chat`} icon={<ChatCircleText className="size-4" aria-hidden />}>
                Ask
              </NavLink>
            </nav>
          </div>
          <h1 className="mt-3 text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Research gaps</h1>
          <p className="mt-3 max-w-[72ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
            {gaps.length > 0 ? (
              <>
                <span className="tabular-nums">{gaps.length}</span> gap{gaps.length === 1 ? "" : "s"} across <span className="tabular-nums">{paperCount}</span> papers:{" "}
                <span className="tabular-nums">{counts.candidate}</span> to review, <span className="tabular-nums">{counts.accepted}</span> accepted,{" "}
                <span className="tabular-nums">{counts.rejected}</span> rejected. Each one keeps the passages it rests on.
              </>
            ) : (
              "What the papers in this workspace leave open, found by rules that compare their research profiles. A gap is kept only with passages from two papers behind it, quoted word for word."
            )}
          </p>
        </header>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>

        {!workspace || gapsQ.data === undefined ? (
          gapsQ.error ? (
            <div className="mt-8 rounded-2xl p-6" style={panel}>
              <InlineError message="Could not load this workspace's gaps." />
              <button type="button" onClick={() => gapsQ.mutate()} className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                Try again
              </button>
            </div>
          ) : (
            <div role="status" className="mt-8 grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
              <span className="sr-only">Loading the gaps…</span>
              <div className="space-y-3">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-28 rounded-2xl motion-safe:animate-pulse" style={panel} />
                ))}
              </div>
              <div className="hidden h-[420px] rounded-2xl motion-safe:animate-pulse lg:block" style={panel} />
            </div>
          )
        ) : members.length < 2 ? (
          <div className="mt-8 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <h2 className="text-lg font-bold">Gaps need two papers</h2>
            <p className="mx-auto mt-2 max-w-[58ch] text-sm leading-relaxed" style={{ color: C.muted }}>
              A gap is what several papers leave open, so this workspace needs more than its seed. Add related papers, then look for gaps.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              <Link href={`/workspace/${id}#papers`} className={`rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                Add papers
              </Link>
              <Link href={`/discover/${workspace.seed_paper_id}`} className={`rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={quietButton}>
                Discover related papers
              </Link>
            </div>
          </div>
        ) : (
          <>
            {/* the run */}
            <section aria-labelledby="gap-run" className="mt-7 rounded-2xl p-5" style={panel}>
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                <div className="min-w-0 flex-1">
                  <h2 id="gap-run" className="text-base font-bold">
                    How gaps are found
                  </h2>
                  <p className="mt-1.5 max-w-[78ch] text-[13.5px] leading-relaxed" style={{ color: C.muted }}>
                    Rules compare the papers&apos; research profiles; a language model only phrases what a rule found, and a gap is kept only if its own
                    passages support it. Gaps you accept or reject are never overwritten.
                    {profilesQ.data && <> {readiness(profilesQ.data, noKey)}</>}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={run}
                  disabled={running || noKey}
                  className={`inline-flex min-h-11 shrink-0 items-center self-start rounded-full px-5 text-sm font-semibold transition-[opacity,transform] active:scale-[0.97] disabled:opacity-45 ${focusRing}`}
                  style={primaryButton}
                >
                  {running ? "Looking…" : gaps.length > 0 ? "Look for gaps again" : "Find gaps"}
                </button>
              </div>
              {noKey && (
                <p className="mt-3 flex items-start gap-1.5 text-[13px] leading-snug" style={{ color: C.warning }}>
                  <Warning className="mt-px size-4 shrink-0" weight="bold" aria-hidden />
                  <span>
                    No working LLM provider key is saved, so a run can&apos;t start yet.{" "}
                    <Link href="/settings#models" className={`rounded-sm font-semibold underline underline-offset-4 ${focusRing}`}>
                      Add a key
                    </Link>
                  </span>
                </p>
              )}
              {running && <RunSteps progress={progress} />}
              {outcome && (
                <div role="status" className="mt-4 border-t pt-4 text-[13.5px] leading-relaxed" style={{ borderColor: C.line }}>
                  <p>
                    {outcome.candidates === 0
                      ? "No rule found a gap in these papers. Rules need papers that share a problem, dataset, metric or limitation, with passages from two of them."
                      : outcome.candidates != null && outcome.kept === 0
                        ? `No new gaps among ${outcome.candidates} candidate${outcome.candidates === 1 ? "" : "s"}.`
                        : outcome.candidates != null
                          ? `Kept ${outcome.kept} of ${outcome.candidates} candidate gap${outcome.candidates === 1 ? "" : "s"}.`
                          : `Found ${outcome.kept} gap${outcome.kept === 1 ? "" : "s"}.`}
                    {outcome.dropped.length > 0 && (
                      <span style={{ color: C.muted }}> {outcome.dropped.map((d) => `${d.count} ${d.reason}`).join("; ")}.</span>
                    )}
                  </p>
                  {(outcome.notChecked > 0 || outcome.rephrased > 0) && (
                    <p className="mt-1" style={{ color: C.muted }}>
                      {outcome.notChecked > 0 &&
                        `${outcome.notChecked} weaker candidate${outcome.notChecked === 1 ? " wasn't" : "s weren't"} checked this run: the strongest rules go first. `}
                      {outcome.rephrased > 0 &&
                        `${outcome.rephrased} ${outcome.rephrased === 1 ? "was" : "were"} phrased in the rule's own words, because the model's wording added something the passages don't contain.`}
                    </p>
                  )}
                  {(outcome.profiled > 0 || outcome.unprofiled > 0 || outcome.profileFailed > 0) && (
                    <p className="mt-1" style={{ color: C.muted }}>
                      {outcome.profiled > 0 && `Read ${outcome.profiled} paper${outcome.profiled === 1 ? "" : "s"} to build a research profile first. `}
                      {outcome.profileFailed > 0 &&
                        `Reading ${outcome.profileFailed} paper${outcome.profileFailed === 1 ? "" : "s"} failed this time; the next run tries again. `}
                      {outcome.unprofiled > 0 &&
                        `${outcome.unprofiled} paper${outcome.unprofiled === 1 ? " has" : "s have"} no profile and no text to read, so no rule could see ${outcome.unprofiled === 1 ? "it" : "them"}.`}
                    </p>
                  )}
                </div>
              )}
              {failure && (
                <div className="mt-4 border-t pt-4" style={{ borderColor: C.line }}>
                  <InlineError message={failure.message} />
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {failure.action === "settings" ? (
                      <Link href="/settings#models" className={`inline-flex min-h-10 items-center rounded-full px-4 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                        Check the key in Settings
                      </Link>
                    ) : (
                      <button
                        type="button"
                        onClick={run}
                        disabled={noKey}
                        className={`inline-flex min-h-10 items-center gap-1.5 rounded-full px-4 text-sm font-semibold transition-transform active:scale-[0.97] disabled:opacity-45 ${focusRing}`}
                        style={primaryButton}
                      >
                        <ArrowCounterClockwise className="size-4" weight="bold" aria-hidden />
                        Run again
                      </button>
                    )}
                  </div>
                  {failure.technical && (
                    <details className="mt-3 text-[12.5px]" style={{ color: C.muted }}>
                      <summary className={`w-fit cursor-pointer rounded-sm hover:text-white ${focusRing}`}>Technical details</summary>
                      <p className="mt-1 font-mono text-[12px] [overflow-wrap:anywhere]">{failure.technical}</p>
                    </details>
                  )}
                </div>
              )}
              {polling.error && !polling.isDone && (
                <div className="mt-4">
                  <InlineError message="Lost track of the run. It may still finish; reload to see its gaps." />
                </div>
              )}
              {runError && (
                <div className="mt-4">
                  <InlineError message={runError} />
                </div>
              )}
            </section>

            {gaps.length === 0 ? (
              !running && (
                <div className="mt-8 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                  <h2 className="text-lg font-bold">No gaps yet</h2>
                  <p className="mx-auto mt-2 max-w-[60ch] text-sm leading-relaxed" style={{ color: C.muted }}>
                    Run the rules over this workspace&apos;s papers. Each gap they find arrives with the passages behind it, to accept or reject.
                  </p>
                </div>
              )
            ) : (
              <div className="mt-8 grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
                <section aria-labelledby="gap-list">
                  <h2 id="gap-list" className="sr-only">
                    Gaps
                  </h2>
                  <Filters filters={filters} onChange={setFilters} counts={counts} types={typesPresent} bands={bandsPresent} />
                  {shown.length === 0 ? (
                    <div className="mt-4 rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                      {filters.state === "candidate" && counts.candidate === 0 && !filters.query && filters.type === "all" && filters.confidence === "all" ? (
                        <>
                          <h3 className="text-base font-bold">Nothing left to review</h3>
                          <p className="mx-auto mt-1.5 max-w-[50ch] text-sm" style={{ color: C.muted }}>
                            Every gap has a decision. Look at what you accepted, or run the rules again after adding papers.
                          </p>
                          <button
                            type="button"
                            onClick={() => setFilters({ ...filters, state: "accepted" })}
                            className={`mt-4 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
                            style={quietButton}
                          >
                            Show accepted gaps
                          </button>
                        </>
                      ) : (
                        <>
                          <h3 className="text-base font-bold">No gaps match</h3>
                          <p className="mx-auto mt-1.5 max-w-[50ch] text-sm" style={{ color: C.muted }}>
                            Nothing here fits these filters.
                          </p>
                          <button
                            type="button"
                            onClick={() => setFilters({ ...NO_FILTERS, state: "all" })}
                            className={`mt-4 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
                            style={quietButton}
                          >
                            Clear the filters
                          </button>
                        </>
                      )}
                    </div>
                  ) : (
                    <ul className="mt-4 space-y-1.5 rounded-2xl p-1.5" style={panel} aria-label={`${listLabel(filters.state)}: ${shown.length} gap${shown.length === 1 ? "" : "s"}`}>
                      {shown.map((g) => (
                        <li key={g.gap_id}>
                          <GapRow gap={g} selected={detail?.gap_id === g.gap_id} onSelect={() => select(g.gap_id)} kindOf={kindOf} />
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                {isWide && (
                  <div
                    className="sticky top-6 max-h-[calc(100dvh-3rem)] overflow-y-auto overscroll-contain rounded-2xl [scrollbar-color:rgba(150,175,230,.28)_transparent]"
                    style={{ background: "rgba(10,15,32,.82)", border: `1px solid ${C.lineStrong}` }}
                    data-testid="gap-detail"
                  >
                    {detail ? (
                      detailFor(detail)
                    ) : (
                      <MissingGap known={selectedId != null} onClear={() => select(null, false)} />
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {sheetOpen && detail && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Gap details"
          className="fixed inset-0 z-40 overflow-y-auto overscroll-contain"
          style={{ background: "#070a16" }}
          data-testid="gap-detail"
        >
          <div className="sticky top-0 z-10 flex items-center border-b px-2 py-1.5 backdrop-blur-md" style={{ borderColor: C.line, background: "rgba(7,10,22,.9)" }}>
            <button
              type="button"
              onClick={closeSheet}
              className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-sm font-semibold hover:bg-white/10 ${focusRing}`}
              style={{ color: C.muted }}
            >
              <ArrowLeft className="size-4" aria-hidden />
              All gaps
            </button>
          </div>
          {detailFor(detail)}
        </div>
      )}
      {!isWide && selectedId && !selected && gapsQ.data && (
        <div className="fixed inset-x-3 bottom-3 z-40 rounded-2xl" style={{ background: "rgba(10,15,32,.96)", border: `1px solid ${C.lineStrong}` }}>
          <MissingGap known onClear={() => select(null, false)} />
        </div>
      )}
    </PageShell>
  );
}

function listLabel(state: GapFilters["state"]): string {
  return state === "all" ? "All gaps" : STATE_LABEL[state];
}

/** Which papers the rules can see, and what a run will read first. */
/** The run's four steps, the current one lit, with how far through it the run is. */
function RunSteps({ progress }: { progress: RunProgress }) {
  const current = RUN_STEPS.findIndex((s) => s.stage === progress.stage);
  const fraction = progress.done != null && progress.total ? progress.done / progress.total : null;
  return (
    <div className="mt-4 border-t pt-4" style={{ borderColor: C.line }}>
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[12.5px]" aria-label="Steps of the run">
        {RUN_STEPS.map((step, i) => {
          const state = current < 0 || i > current ? "todo" : i < current ? "done" : "now";
          return (
            <li key={step.stage} className="flex items-center gap-2" aria-current={state === "now" ? "step" : undefined}>
              {i > 0 && <span className="h-px w-5" style={{ background: state === "todo" ? C.line : "rgba(93,240,168,.45)" }} aria-hidden />}
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold"
                style={
                  state === "now"
                    ? { color: C.mint, background: "rgba(93,240,168,.1)", border: "1px solid rgba(93,240,168,.35)" }
                    : { color: state === "done" ? C.muted : C.muted2, border: `1px solid ${C.line}` }
                }
              >
                {state === "done" && <Check className="size-3" weight="bold" aria-hidden />}
                {step.label}
                <span className="sr-only">{state === "done" ? " (done)" : state === "now" ? " (in progress)" : ""}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <p role="status" className="mt-3 text-[13px]" style={{ color: C.muted }}>
        {progress.label}…
      </p>
      {fraction != null && (
        <div className="mt-2 flex items-center gap-3">
          <div
            role="progressbar"
            aria-label={progress.label}
            aria-valuemin={0}
            aria-valuemax={progress.total ?? 0}
            aria-valuenow={progress.done ?? 0}
            className="h-1 flex-1 overflow-hidden rounded-full"
            style={{ background: "rgba(150,175,230,.12)" }}
          >
            <div
              className="h-full rounded-full transition-[width] duration-500 ease-out"
              style={{ width: `${Math.round(fraction * 100)}%`, background: `linear-gradient(90deg, ${C.mint2}, ${C.mint})` }}
            />
          </div>
          <span className="shrink-0 font-mono text-[12px] tabular-nums" style={{ color: C.muted }} aria-hidden>
            {progress.done} of {progress.total}
          </span>
        </div>
      )}
      <p className="mt-2 text-[12.5px]" style={{ color: C.muted2 }}>
        You can leave this page; the run keeps going, and each paper it reads is kept even if the run stops.
      </p>
    </div>
  );
}

function readiness(grounding: Record<string, string | null>, noKey: boolean): string {
  const all = Object.values(grounding);
  const missing = all.filter((g) => g == null).length;
  const fromAbstract = all.filter((g) => g === "abstract").length;
  if (missing === 0) {
    return fromAbstract > 0
      ? `Every paper here has a profile; ${fromAbstract} of them ${fromAbstract === 1 ? "was" : "were"} read from an abstract only, which lowers confidence.`
      : "Every paper here has a research profile.";
  }
  const had = all.length - missing;
  const lead = `${had} of ${all.length} papers ${had === 1 ? "has" : "have"} a research profile`;
  return noKey
    ? `${lead}; the ${missing === 1 ? "other needs" : `other ${missing} need`} a model to read ${missing === 1 ? "its" : "their"} text first.`
    : `${lead}; a run reads the ${missing === 1 ? "other one's" : `other ${missing}'s`} text first (an abstract when that is all there is).`;
}

function MissingGap({ known, onClear }: { known: boolean; onClear: () => void }) {
  return (
    <div className="px-6 py-10 text-center">
      <p className="text-sm" style={{ color: C.muted }}>
        {known ? "That gap isn't in this workspace any more; a later run replaced it." : "Choose a gap to read its evidence."}
      </p>
      {known && (
        <button type="button" onClick={onClear} className={`mt-3 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={quietButton}>
          Show all gaps
        </button>
      )}
    </div>
  );
}

function Filters({
  filters,
  onChange,
  counts,
  types,
  bands,
}: {
  filters: GapFilters;
  onChange: (f: GapFilters) => void;
  counts: Record<GapUserState | "all", number>;
  types: GapType[];
  bands: Confidence[];
}) {
  const states: (GapUserState | "all")[] = ["candidate", "accepted", "rejected", "all"];
  const selectCls = `min-h-11 rounded-full bg-transparent px-3 text-[13px] [color-scheme:dark] sm:min-h-9 ${focusRing}`;
  return (
    <div className="space-y-2.5">
      <div role="group" aria-label="Show gaps" className="flex flex-wrap gap-1.5">
        {states.map((s) => {
          const on = filters.state === s;
          return (
            <button
              key={s}
              type="button"
              aria-pressed={on}
              onClick={() => onChange({ ...filters, state: s })}
              className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors sm:min-h-9 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
              style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
            >
              {s === "all" ? "All" : STATE_LABEL[s]}
              <span className="tabular-nums" style={{ opacity: 0.75 }}>
                {counts[s]}
              </span>
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <label className="relative flex min-w-[200px] flex-1 items-center">
          <span className="sr-only">Search the gaps</span>
          <MagnifyingGlass className="pointer-events-none absolute left-3 size-4" style={{ color: C.muted }} aria-hidden />
          <input
            type="search"
            value={filters.query}
            onChange={(e) => onChange({ ...filters, query: e.target.value })}
            placeholder="Search statements, terms, passages"
            className={`min-h-11 w-full rounded-full bg-transparent pl-9 pr-3 text-[13.5px] caret-[#5df0a8] outline-none placeholder:text-[#8f9bb8] sm:min-h-9 ${focusRing}`}
            style={{ ...quietButton, color: C.ink }}
          />
        </label>
        {types.length > 1 && (
          <label>
            <span className="sr-only">Gap type</span>
            <select
              value={filters.type}
              onChange={(e) => onChange({ ...filters, type: e.target.value as GapFilters["type"] })}
              className={selectCls}
              style={{ ...quietButton, color: C.ink }}
            >
              <option value="all">Every type</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {GAP_TYPE_LABEL[t] ?? t}
                </option>
              ))}
            </select>
          </label>
        )}
        {bands.length > 1 && (
          <label>
            <span className="sr-only">Confidence</span>
            <select
              value={filters.confidence}
              onChange={(e) => onChange({ ...filters, confidence: e.target.value as GapFilters["confidence"] })}
              className={selectCls}
              style={{ ...quietButton, color: C.ink }}
            >
              <option value="all">Any confidence</option>
              {bands.map((b) => (
                <option key={b} value={b}>
                  {CONFIDENCE_LABEL[b]}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </div>
  );
}

function NavLink({ href, icon, children }: { href: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Link href={href} className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm hover:text-white sm:min-h-0 ${focusRing}`}>
      {icon}
      {children}
    </Link>
  );
}
