"use client";

import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { motion, useReducedMotion } from "motion/react";
import {
  ArrowRight,
  ChatCircleText,
  Check,
  CheckCircle,
  GitBranch,
  Graph,
  Plus,
  Quotes,
  UploadSimple,
  Warning,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react/dist/ssr";
import { papers as papersApi, usage as usageApi, workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { latestComparisonOrNull } from "@/lib/compare";
import { compactTokens, featureLabel, formatTokens, plural } from "@/lib/usage";
import { Reveal } from "@/components/effects/Reveal";
import { Timestamp } from "@/components/ui/Timestamp";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { coverageShort } from "@/lib/coverage";
import { AddPapersPanel } from "./AddPapersPanel";
import { CoverageSummary } from "./CoverageSummary";
import { PaperAnnotations } from "./PaperNotes";
import { C, InlineError, WorkspaceLoadError, focusRing, panel, primaryButton, quietButton } from "./ui";
import {
  STAGE_LABEL,
  buildStations,
  nextStation,
  type Loadable,
  type Station,
} from "@/lib/workspace-overview";
import type {
  ComparisonResponse,
  GroupedTrail,
  RelationshipType,
  ResearchDirection,
  ResearchGap,
  StageName,
  Workspace,
  WorkspacePaper,
} from "@/lib/api/types";

// The panel surface nodes sit on -- opaque so a node hides the track behind it.
const NODE_BG = "#0b1020";

const RELATIONSHIP_LABEL: Record<RelationshipType, string> = {
  SIMILAR: "similar",
  FOUNDATIONAL: "foundational",
  RECENT: "recent",
  COMPETING: "competing",
  METHOD_EXTENSION: "method extension",
  DATASET_RELATED: "dataset-related",
  POTENTIALLY_CONTRADICTORY: "potentially contradictory",
};

function toLoadable<T>(q: { data?: T; error?: unknown }): Loadable<T> {
  if (q.error) return { status: "error" };
  if (q.data === undefined) return { status: "loading" };
  return { status: "ready", data: q.data };
}

/** A workspace section's link. `base` is the legacy /workspaces/{id} root;
 * sections rebuilt in the cinematic app live under /workspace/{id}. */
function sectionHref(base: string, slug: string): string {
  return `${base}/${slug}`;
}

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`motion-safe:animate-pulse rounded-2xl ${className}`} style={panel} />;
}

function SectionHeading({ id, children, action }: { id: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 id={id} tabIndex={-1} className="text-lg font-bold tracking-[-0.01em] outline-none">
        {children}
      </h2>
      {action}
    </div>
  );
}

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const { me } = useAuth();

  const {
    data: workspace,
    error: workspaceError,
    mutate: mutateWorkspace,
  } = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));

  const live = ready && !!workspace;
  const trailQ = useSWR(live ? ["ws-trail", id] : null, () => workspaces.trail(id));
  // Only ask for the latest comparison when one exists: the endpoint answers
  // 404 otherwise, which the browser logs as a console error.
  const hasComparison = (workspace?.counts?.comparisons ?? 1) > 0;
  const comparisonQ = useSWR(live && hasComparison ? ["ws-latest-comparison", id] : null, () => latestComparisonOrNull(id));
  const gapsQ = useSWR(live ? ["ws-gaps", id] : null, () => workspaces.listGaps(id));
  const directionsQ = useSWR(live ? ["ws-directions", id] : null, () => workspaces.listDirections(id));
  const chatQ = useSWR(live ? ["ws-chat-sessions", id] : null, () => workspaces.chatSessions(id));
  const activityQ = useSWR(live ? ["ws-activity", id] : null, () => workspaces.activity(id, { limit: 6 }));

  const stations = useMemo(() => {
    if (!workspace) return [];
    return buildStations({
      papers: workspace.papers,
      trail: toLoadable<GroupedTrail>(trailQ),
      comparison: hasComparison
        ? toLoadable<ComparisonResponse | null>(comparisonQ)
        : { status: "ready", data: null },
      gaps: toLoadable<ResearchGap[]>({ data: gapsQ.data?.gaps, error: gapsQ.error }),
      directions: toLoadable<ResearchDirection[]>({ data: directionsQ.data?.directions, error: directionsQ.error }),
    });
  }, [workspace, trailQ, hasComparison, comparisonQ, gapsQ.data, gapsQ.error, directionsQ.data, directionsQ.error]);

  async function refreshAfterMembershipChange() {
    // Adding a paper auto-accepts its pending trail edge and every change
    // re-indexes the workspace, so the trail and activity move with it.
    await Promise.all([mutateWorkspace(), trailQ.mutate(), activityQ.mutate()]);
  }

  if (!ready) return null;

  if (workspaceError) {
    return (
      <PageShell>
        <WorkspaceLoadError error={workspaceError} onRetry={() => mutateWorkspace()} />
      </PageShell>
    );
  }

  if (!workspace) {
    return (
      <PageShell>
        <div role="status" className="space-y-6">
          <span className="sr-only">Loading workspace…</span>
          <Skeleton className="h-20 w-full max-w-2xl" />
          <Skeleton className="h-36 w-full" />
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
            <Skeleton className="h-72" />
            <Skeleton className="h-72" />
          </div>
        </div>
      </PageShell>
    );
  }

  const base = `/workspace/${id}`;
  const next = nextStation(stations);

  return (
    <PageShell>
      <div className="selection:bg-[rgba(93,240,168,0.28)] selection:text-white">
        <WorkspaceHeader workspace={workspace} base={base} />

        {me && !me.has_working_llm_key && (
          <div
            className="mt-6 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl px-5 py-3.5 text-sm"
            style={{ background: "rgba(232,193,92,.08)", border: "1px solid rgba(232,193,92,.25)", color: C.warning }}
          >
            <Warning className="size-4 shrink-0" weight="bold" aria-hidden />
            <span>No working LLM provider key is saved. Chat, comparison, gaps, and directions need one.</span>
            <Link href="/settings" className={`ml-auto shrink-0 rounded-sm font-semibold underline underline-offset-4 ${focusRing}`}>
              Add a key
            </Link>
          </div>
        )}

        <ResearchPath stations={stations} next={next} base={base} />

        <div className="mt-12 grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-10">
          <PapersSection workspace={workspace} onChanged={refreshAfterMembershipChange} />
          <aside className="space-y-12" aria-label="Workspace tools and history">
            <GoDeeper
              base={base}
              trail={trailQ.data}
              chatCount={chatQ.data?.sessions.length}
              paperCount={workspace.papers.length}
            />
            <Decisions base={base} gaps={gapsQ.data?.gaps} directions={directionsQ.data?.directions} />
            <RecentActivity base={base} activity={activityQ.data?.stage_runs} error={!!activityQ.error} />
          </aside>
        </div>
      </div>
    </PageShell>
  );
}

function WorkspaceHeader({ workspace, base }: { workspace: Workspace; base: string }) {
  const { data: seed } = useSWR(["paper", workspace.seed_paper_id], () => papersApi.get(workspace.seed_paper_id));

  return (
    <Reveal>
      <header className="flex flex-col gap-6 border-b pb-8 lg:flex-row lg:items-end lg:justify-between" style={{ borderColor: C.lineStrong }}>
        <div className="min-w-0 max-w-3xl">
          <h1 className="text-balance text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">{workspace.title}</h1>
          <p className="mt-3 text-[15px] leading-relaxed" style={{ color: C.muted }}>
            Seeded from{" "}
            <Link
              href={`/seed/${workspace.seed_paper_id}`}
              className={`rounded-sm font-medium underline decoration-[rgba(93,240,168,0.45)] underline-offset-4 transition-colors hover:text-white ${focusRing}`}
              style={{ color: C.ink }}
            >
              {seed?.title ?? "the seed paper"}
            </Link>
            <span aria-hidden> · </span>
            <span className="whitespace-nowrap">
              created <Timestamp at={workspace.created_at} style="date" />
            </span>
          </p>
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-end lg:shrink-0 lg:flex-col lg:items-end">
          <WorkspaceUsage workspaceId={workspace.workspace_id} />
          <div className="flex flex-wrap gap-2 lg:justify-end">
            {workspace.source_run_id && (
              <Link
                href={`/discover/${workspace.seed_paper_id}?run=${workspace.source_run_id}`}
                className={`rounded-full px-4 py-2.5 text-sm font-semibold transition-colors hover:bg-white/10 ${focusRing}`}
                style={quietButton}
              >
                Discovery results
              </Link>
            )}
            <Link
              href={sectionHref(base, "chat")}
              className={`inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`}
              style={primaryButton}
            >
              <ChatCircleText className="size-4" weight="bold" aria-hidden />
              Ask this workspace
            </Link>
          </div>
        </div>
      </header>
    </Reveal>
  );
}

/** What the models used in this workspace lately: the provider's own token
 * counts from the usage ledger, never a cost (remediation Phase 5). */
function WorkspaceUsage({ workspaceId }: { workspaceId: string }) {
  const { data, error } = useSWR(["usage", "30d", workspaceId], () => usageApi.get("30d", workspaceId));
  const top = data?.by_feature.filter((f) => f.total_tokens > 0).slice(0, 2) ?? [];

  return (
    <div className="min-w-[180px] text-sm lg:text-right" data-testid="workspace-usage">
      {error ? (
        <p style={{ color: C.muted }}>Model usage is unavailable right now.</p>
      ) : !data ? (
        <p role="status" className="h-10 w-48 rounded-lg motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.05)" }}>
          <span className="sr-only">Loading model usage…</span>
        </p>
      ) : data.totals.calls === 0 ? (
        <p style={{ color: C.muted }}>No model calls in the last 30 days</p>
      ) : (
        <>
          <p className="tabular-nums" style={{ color: C.muted }} title={`${formatTokens(data.totals.total_tokens)} tokens across ${plural(data.totals.calls, "call")}`}>
            <span className="font-semibold" style={{ color: C.ink }}>
              {compactTokens(data.totals.total_tokens)} tokens
            </span>{" "}
            in the last 30 days
          </p>
          {top.length > 0 && (
            <p className="mt-0.5 text-[13px] tabular-nums" style={{ color: C.muted }}>
              {top.map((f) => `${featureLabel(f.feature)} ${compactTokens(f.total_tokens)}`).join(" · ")}
            </p>
          )}
        </>
      )}
      <Link href="/settings#usage" className={`mt-1 inline-block rounded-sm text-[13px] font-medium hover:text-white ${focusRing}`} style={{ color: C.mint }}>
        Usage details
      </Link>
    </div>
  );
}

const STATE_TEXT: Record<Station["state"], string> = {
  done: "done",
  review: "needs review",
  todo: "not started",
  loading: "loading",
  error: "unavailable",
};

function StationNode({ station, isNext }: { station: Station; isNext: boolean }) {
  const ring =
    station.state === "review" ? C.warning : station.state === "error" ? C.danger : isNext ? C.mint : C.lineStrong;
  return (
    <span
      className={`relative z-[1] flex size-8 shrink-0 items-center justify-center rounded-full ${station.state === "loading" ? "motion-safe:animate-pulse" : ""}`}
      style={
        station.state === "done"
          ? { background: C.mint, color: C.mintInk }
          : { background: NODE_BG, border: `1.5px solid ${ring}`, boxShadow: isNext ? "0 0 0 5px rgba(93,240,168,.12)" : undefined }
      }
      aria-hidden
    >
      {station.state === "done" && <Check className="size-4" weight="bold" />}
      {station.state === "review" && <span className="size-2 rounded-full" style={{ background: C.warning }} />}
      {station.state === "error" && <WarningCircle className="size-4" style={{ color: C.danger }} weight="bold" />}
    </span>
  );
}

/** The one authored motion on this page: the track fills to the last
 * consecutively completed stage, so progress reads as distance travelled
 * along the research path rather than as a score. */
function ResearchPath({ stations, next, base }: { stations: Station[]; next: Station | null; base: string }) {
  const reduce = useReducedMotion();
  let reached = -1;
  for (const s of stations) {
    if (s.state !== "done") break;
    reached += 1;
  }
  const span = stations.length - 1;
  const fill = span > 0 ? Math.max(0, reached) / span : 0;
  const transition = { duration: reduce ? 0 : 0.9, ease: [0.16, 1, 0.3, 1] as const, delay: reduce ? 0 : 0.15 };

  return (
    <section aria-labelledby="path-heading" className="mt-10">
      <h2 id="path-heading" className="text-lg font-bold tracking-[-0.01em]">
        Where this research stands
      </h2>
      <div className="mt-4 rounded-2xl px-5 py-6 sm:px-6" style={panel}>
        <div className="relative">
          {/* horizontal track (desktop) */}
          <span aria-hidden className="absolute left-[10%] right-[10%] top-4 hidden h-px lg:block" style={{ background: C.lineStrong }} />
          <motion.span
            aria-hidden
            className="absolute left-[10%] top-4 hidden h-px origin-left lg:block"
            style={{ width: `${fill * 80}%`, background: C.mint }}
            initial={{ scaleX: reduce ? 1 : 0 }}
            animate={{ scaleX: 1 }}
            transition={transition}
          />
          {/* vertical track (mobile) */}
          <span aria-hidden className="absolute bottom-4 left-4 top-4 w-px lg:hidden" style={{ background: C.lineStrong }} />
          <motion.span
            aria-hidden
            className="absolute left-4 top-4 w-px origin-top lg:hidden"
            style={{ height: `calc((100% - 2rem) * ${fill})`, background: C.mint }}
            initial={{ scaleY: reduce ? 1 : 0 }}
            animate={{ scaleY: 1 }}
            transition={transition}
          />
          <ol className="relative grid gap-5 lg:grid-cols-5 lg:gap-3">
          {stations.map((s) => {
            const isNext = next?.key === s.key;
            const href = s.key === "papers" ? "#papers" : sectionHref(base, s.slug);
            return (
              <li key={s.key} className="relative">
                <Link
                  href={href}
                  className={`group flex gap-4 rounded-xl lg:flex-col lg:items-center lg:gap-3 lg:text-center ${focusRing}`}
                >
                  <StationNode station={s} isNext={isNext} />
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold transition-colors group-hover:text-white" style={{ color: C.ink }}>
                      {s.label}
                      <span className="sr-only">: {STATE_TEXT[s.state]}</span>
                    </span>
                    <span className="mt-0.5 block text-sm tabular-nums" style={{ color: s.state === "done" ? C.ink : C.muted }}>
                      {s.value}
                    </span>
                    {s.detail && (
                      <span className="mt-0.5 block text-[13px]" style={{ color: s.state === "review" ? C.warning : C.muted }}>
                        {s.detail}
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            );
          })}
          </ol>
        </div>

        {next && (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t pt-5" style={{ borderColor: C.line }}>
            <p className="text-sm" style={{ color: C.muted }}>
              <span className="font-semibold" style={{ color: C.ink }}>
                Next: {next.action.toLowerCase()}.
              </span>{" "}
              {next.detail}
            </p>
            <Link
              href={next.key === "papers" ? "#papers" : sectionHref(base, next.slug)}
              className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
              style={primaryButton}
            >
              {next.action}
              <ArrowRight className="size-4" weight="bold" aria-hidden />
            </Link>
          </div>
        )}
      </div>
    </section>
  );
}

function sortPapers(list: WorkspacePaper[]): WorkspacePaper[] {
  return [...list].sort((a, b) => {
    if (a.role !== b.role) return a.role === "seed" ? -1 : 1;
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    const ra = a.ranking_snapshot?.final_rank ?? Number.POSITIVE_INFINITY;
    const rb = b.ranking_snapshot?.final_rank ?? Number.POSITIVE_INFINITY;
    if (ra !== rb) return ra - rb;
    return a.added_at.localeCompare(b.added_at);
  });
}

function PapersSection({ workspace, onChanged }: { workspace: Workspace; onChanged: () => Promise<void> }) {
  const [adding, setAdding] = useState(false);
  const [opened, setOpened] = useState(false);
  const panelId = useId();

  function toggleAdding(next: boolean) {
    setAdding(next);
    if (next) setOpened(true);
  }
  const sorted = sortPapers(workspace.papers);
  const onlySeed = sorted.length === 1;

  return (
    <section aria-labelledby="papers-heading" id="papers" className="min-w-0 scroll-mt-8">
      <SectionHeading
        id="papers-heading"
        action={
          <button
            type="button"
            onClick={() => toggleAdding(!adding)}
            aria-expanded={adding}
            aria-controls={panelId}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold transition-colors hover:bg-white/10 sm:min-h-0 ${focusRing}`}
            style={quietButton}
          >
            {adding ? <Check className="size-4" weight="bold" aria-hidden /> : <Plus className="size-4" weight="bold" aria-hidden />}
            {adding ? "Done adding" : "Add papers"}
          </button>
        }
      >
        Papers <span className="ml-1 font-semibold tabular-nums" style={{ color: C.muted }}>{sorted.length}</span>
      </SectionHeading>

      <div id={panelId} hidden={!adding}>
        {opened && <AddPapersPanel key={workspace.workspace_id} workspace={workspace} onAdded={onChanged} />}
      </div>

      <CoverageSummary workspaceId={workspace.workspace_id} paperCount={workspace.papers.length} />
      <ul className="overflow-hidden rounded-2xl" style={panel}>
        {sorted.map((p, i) => (
          <PaperRow key={p.paper_id} workspaceId={workspace.workspace_id} paper={p} first={i === 0} onRemoved={onChanged} />
        ))}
      </ul>

      {onlySeed && !adding && (
        <p className="mt-4 text-sm" style={{ color: C.muted }}>
          Only the seed paper so far.{" "}
          <button
            type="button"
            onClick={() => toggleAdding(true)}
            className={`rounded-sm font-semibold underline underline-offset-4 hover:text-white ${focusRing}`}
            style={{ color: C.mint }}
          >
            Add related papers
          </button>{" "}
          to start comparing and finding gaps.
        </p>
      )}
    </section>
  );
}

function PaperRow({
  workspaceId,
  paper,
  first,
  onRemoved,
}: {
  workspaceId: string;
  paper: WorkspacePaper;
  first: boolean;
  onRemoved: () => Promise<void>;
}) {
  const { data: detail, error: detailError, mutate: mutateDetail } = useSWR(["paper", paper.paper_id], () => papersApi.get(paper.paper_id));
  const [confirming, setConfirming] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploaded, setUploaded] = useState<string | null>(null);
  const pdfRef = useRef<HTMLInputElement>(null);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);
  const isSeed = paper.role === "seed";

  // The confirm controls replace the trigger in place, so focus has to be
  // moved explicitly or keyboard users are dropped back to the page top.
  useEffect(() => {
    if (confirming) keepRef.current?.focus();
    else if (wasConfirming.current) triggerRef.current?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);
  const title = detail?.title ?? (detailError ? paper.paper_id : null);
  const href = isSeed ? `/seed/${paper.paper_id}` : `/papers/${paper.paper_id}`;

  async function remove() {
    setRemoving(true);
    setError(null);
    try {
      await workspaces.removePaper(workspaceId, paper.paper_id);
      await onRemoved();
      // this row is gone now; land focus on the list's heading instead
      document.getElementById("papers-heading")?.focus();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}.` : "Could not remove this paper. Try again.");
      setRemoving(false);
      setConfirming(false);
    }
  }

  // a paper read from its abstract only can take the reader's own PDF (2026-10-02)
  async function uploadPdf(file: File) {
    setUploading(true);
    setError(null);
    setUploaded(null);
    try {
      const res = await papersApi.uploadPdf(paper.paper_id, file);
      setUploaded(`Full text read from your PDF: ${res.outcome.chunks} passages.`);
      await mutateDetail();
      await onRemoved(); // the workspace's coverage counts change too
    } catch (err) {
      setError(err instanceof ApiError ? `That PDF couldn't be used: ${err.message}.` : "The server couldn't be reached. Try again.");
    } finally {
      setUploading(false);
      if (pdfRef.current) pdfRef.current.value = "";
    }
  }

  const authors = detail?.authors ?? [];
  const byline = [
    authors.length > 3 ? `${authors.slice(0, 3).join(", ")} et al.` : authors.join(", "),
    detail?.venue,
    detail?.publisher && detail.publisher !== detail.venue ? detail.publisher : null,
    detail?.year != null ? String(detail.year) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const snapshot = paper.ranking_snapshot;
  const provenance = [
    isSeed ? "Seed paper" : paper.added_by === "trail" ? "Added from discovery" : "Added manually",
    snapshot ? `ranked #${snapshot.final_rank}, ${snapshot.band} confidence` : null,
    // the text it is read from, as the paper itself says (its full text may have been found since it joined)
    detail?.coverage ? coverageShort(detail.coverage.state) : paper.grounding === "full_text" ? "full text" : "abstract only",
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className={first ? "" : "border-t"} style={{ borderColor: C.line }}>
      <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0 flex-1">
          {title === null ? (
            <div role="status" className="h-5 w-3/4 rounded motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.08)" }}>
              <span className="sr-only">Loading paper details…</span>
            </div>
          ) : (
            <Link
              href={href}
              className={`rounded-sm text-[15px] font-semibold leading-snug transition-colors hover:text-white hover:underline hover:underline-offset-4 ${focusRing}`}
              style={{ color: C.ink }}
            >
              {isSeed && (
                <>
                  {/* a real space (not just margin) so the link's accessible name reads "Seed <title>" */}
                  <span className="mr-1 align-[1px] text-xs font-bold uppercase tracking-wider" style={{ color: C.mint }}>
                    Seed
                  </span>{" "}
                </>
              )}
              {title}
            </Link>
          )}
          {byline && (
            <p className="mt-1 text-sm" style={{ color: C.muted }}>
              {byline}
            </p>
          )}
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[13px]" style={{ color: C.muted }}>
            {provenance}
          </p>
          {paper.note && (
            <p className="mt-2 max-w-[70ch] whitespace-pre-line text-sm leading-relaxed" style={{ color: C.ink }}>
              {paper.note}
            </p>
          )}
          {title !== null && <PaperAnnotations workspaceId={workspaceId} paper={paper} title={title} onSaved={onRemoved} />}
          {error && (
            <div className="mt-2">
              <InlineError message={error} />
            </div>
          )}
          {uploaded && (
            <p role="status" className="mt-2 text-sm" style={{ color: C.mint }}>
              {uploaded}
            </p>
          )}
        </div>

        {!isSeed && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {detail?.coverage && detail.coverage.state !== "full_text" && !confirming && (
              <>
                <input
                  ref={pdfRef}
                  type="file"
                  accept="application/pdf,.pdf"
                  className="sr-only"
                  tabIndex={-1}
                  aria-hidden
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void uploadPdf(file);
                  }}
                />
                <button
                  type="button"
                  onClick={() => pdfRef.current?.click()}
                  disabled={uploading}
                  aria-label={`Upload the PDF of ${title ?? paper.paper_id}`}
                  className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors hover:bg-white/10 hover:text-white disabled:opacity-60 sm:min-h-0 ${focusRing}`}
                  style={{ color: C.muted }}
                >
                  <UploadSimple className="size-4" aria-hidden />
                  {uploading ? "Reading…" : "Upload PDF"}
                </button>
              </>
            )}
            {confirming ? (
              <>
                <span className="text-sm" style={{ color: C.muted }}>
                  Remove from workspace?
                </span>
                <button
                  type="button"
                  onClick={remove}
                  disabled={removing}
                  className={`inline-flex min-h-11 items-center rounded-full px-3.5 py-1.5 text-sm font-semibold disabled:opacity-60 sm:min-h-0 ${focusRing}`}
                  style={{ color: "#2a0606", background: C.danger }}
                >
                  {removing ? "Removing…" : "Remove"}
                </button>
                <button
                  ref={keepRef}
                  type="button"
                  onClick={() => setConfirming(false)}
                  disabled={removing}
                  className={`inline-flex min-h-11 items-center rounded-full px-3.5 py-1.5 text-sm font-semibold transition-colors hover:bg-white/10 disabled:opacity-60 sm:min-h-0 ${focusRing}`}
                  style={quietButton}
                >
                  Keep
                </button>
              </>
            ) : (
              <button
                ref={triggerRef}
                type="button"
                onClick={() => setConfirming(true)}
                aria-label={`Remove ${title ?? paper.paper_id} from workspace`}
                className={`-ml-3.5 inline-flex min-h-11 items-center rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors hover:bg-white/10 hover:text-white sm:ml-0 sm:min-h-0 ${focusRing}`}
                style={{ color: C.muted }}
              >
                Remove
              </button>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

function trailSummary(trail: GroupedTrail | undefined): string {
  if (!trail) return "Typed relationships to the seed paper";
  const counts = (Object.entries(trail.groups) as [RelationshipType, unknown[]][])
    .map(([type, entries]) => [type, entries.length] as const)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
  if (counts.length === 0) return "No connections to the seed yet";
  return counts
    .slice(0, 3)
    .map(([type, n]) => `${n} ${RELATIONSHIP_LABEL[type]}`)
    .join(" · ");
}

function GoDeeper({
  base,
  trail,
  chatCount,
  paperCount,
}: {
  base: string;
  trail: GroupedTrail | undefined;
  chatCount: number | undefined;
  paperCount: number;
}) {
  const rows = [
    { href: sectionHref(base, "trail"), icon: GitBranch, title: "Research trail", detail: trailSummary(trail) },
    { href: sectionHref(base, "graph"), icon: Graph, title: "Research graph", detail: "Papers and their connections on one map, through time" },
    {
      href: sectionHref(base, "chat"),
      icon: ChatCircleText,
      title: "Chat",
      detail:
        chatCount === undefined || chatCount === 0
          ? "Answers cite the exact passage they rest on"
          : `${chatCount} conversation${chatCount === 1 ? "" : "s"} so far`,
    },
    { href: sectionHref(base, "citations"), icon: Quotes, title: "Citations", detail: `Where the workspace cites each of its ${paperCount} paper${paperCount === 1 ? "" : "s"}, with references to copy` },
  ];

  return (
    <section aria-labelledby="deeper-heading">
      <SectionHeading id="deeper-heading">Go deeper</SectionHeading>
      <ul className="overflow-hidden rounded-2xl" style={panel}>
        {rows.map((row, i) => (
          <li key={row.href} className={i === 0 ? "" : "border-t"} style={{ borderColor: C.line }}>
            <Link href={row.href} className={`group flex items-center gap-3.5 px-4 py-3.5 transition-colors hover:bg-white/[0.04] ${focusRing}`}>
              <row.icon className="size-5 shrink-0" style={{ color: C.mint }} aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold">{row.title}</span>
                <span className="block text-[13px] leading-snug" style={{ color: C.muted }}>
                  {row.detail}
                </span>
              </span>
              <ArrowRight className="size-4 shrink-0 transition-transform duration-200 group-hover:translate-x-0.5" style={{ color: C.muted }} aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Decisions({ base, gaps, directions }: { base: string; gaps: ResearchGap[] | undefined; directions: ResearchDirection[] | undefined }) {
  const acceptedGaps = (gaps ?? []).filter((g) => g.user_state === "accepted").slice(0, 2);
  const acceptedDirections = (directions ?? []).filter((d) => d.user_state === "accepted").slice(0, 1);
  if (acceptedGaps.length === 0 && acceptedDirections.length === 0) return null;

  return (
    <section aria-labelledby="decisions-heading">
      <SectionHeading id="decisions-heading">Decisions so far</SectionHeading>
      <ul className="space-y-4">
        {acceptedGaps.map((g) => (
          <li key={g.gap_id}>
            <Link href={`${sectionHref(base, "gaps")}?gap=${encodeURIComponent(g.gap_id)}`} className={`group block rounded-xl ${focusRing}`}>
              <span className="text-[13px] font-semibold" style={{ color: C.mint }}>
                Accepted gap · {g.gap_type.replace(/_/g, " ").toLowerCase()}
              </span>
              <span className="mt-1 block text-sm leading-relaxed transition-colors group-hover:text-white" style={{ color: C.ink }}>
                {g.statement}
              </span>
            </Link>
          </li>
        ))}
        {acceptedDirections.map((d) => (
          <li key={d.direction_id}>
            <Link href={`${sectionHref(base, "directions")}?direction=${encodeURIComponent(d.direction_id)}`} className={`group block rounded-xl ${focusRing}`}>
              <span className="text-[13px] font-semibold" style={{ color: C.mint }}>
                Accepted direction
              </span>
              <span className="mt-1 block text-sm leading-relaxed transition-colors group-hover:text-white" style={{ color: C.ink }}>
                {d.proposal}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RecentActivity({
  base,
  activity,
  error,
}: {
  base: string;
  activity: { id: string; stage: StageName; tool: string; ok: boolean; tokens_prompt: number; tokens_completion: number; ts: string; error: string | null }[] | undefined;
  error: boolean;
}) {
  return (
    <section aria-labelledby="activity-heading">
      <SectionHeading
        id="activity-heading"
        action={
          <Link href={`${base}/activity`} className={`rounded-sm text-sm font-medium hover:text-white ${focusRing}`} style={{ color: C.mint }}>
            Full log
          </Link>
        }
      >
        Recent activity
      </SectionHeading>
      {error ? (
        <InlineError message="Could not load recent activity. Refresh to try again." />
      ) : activity === undefined ? (
        <div role="status" className="space-y-2">
          <span className="sr-only">Loading recent activity…</span>
          <div className="h-10 motion-safe:animate-pulse rounded-xl" style={{ background: "rgba(255,255,255,.05)" }} />
          <div className="h-10 motion-safe:animate-pulse rounded-xl" style={{ background: "rgba(255,255,255,.05)" }} />
        </div>
      ) : activity.length === 0 ? (
        <p className="text-sm" style={{ color: C.muted }}>
          Nothing has run in this workspace yet.
        </p>
      ) : (
        <ol className="space-y-3">
          {activity.map((run) => (
            <li key={run.id} className="flex gap-3 text-sm">
              {run.ok ? (
                <CheckCircle className="mt-0.5 size-4 shrink-0" style={{ color: C.mint }} weight="fill" aria-hidden />
              ) : (
                <XCircle className="mt-0.5 size-4 shrink-0" style={{ color: C.danger }} weight="fill" aria-hidden />
              )}
              <div className="min-w-0 flex-1">
                <p style={{ color: C.ink }}>
                  <span className="sr-only">{run.ok ? "Succeeded: " : "Failed: "}</span>
                  {STAGE_LABEL[run.stage] ?? run.stage}
                </p>
                <p className="text-[13px] tabular-nums" style={{ color: C.muted }}>
                  <Timestamp at={run.ts} />
                  {run.tokens_prompt + run.tokens_completion > 0 && ` · ${plural(run.tokens_prompt + run.tokens_completion, "token")}`}
                  {!run.ok && run.error && ` · ${run.error}`}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
