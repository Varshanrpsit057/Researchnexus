"use client";

import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import {
  ArrowSquareOut,
  CaretDown,
  Check,
  Compass,
  WarningCircle,
} from "@phosphor-icons/react/dist/ssr";
import { papers, workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { useJobPolling } from "@/lib/api/hooks";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { CINEMATIC } from "@/lib/cinematic-theme";
import { Reveal } from "@/components/effects/Reveal";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { CinematicDialog, type CinematicDialogHandle } from "@/components/ui/CinematicDialog";
import type { Confidence, CitationRelationship, RelatedResult } from "@/lib/api/types";

const C = CINEMATIC;

function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-2xl ${className}`} style={{ background: C.glass, border: `1px solid ${C.line}` }} />;
}

function InlineError({ message }: { message: string }) {
  return (
    <p role="alert" className="flex items-center gap-1.5 text-sm" style={{ color: C.danger }}>
      <WarningCircle className="size-4 shrink-0" weight="bold" aria-hidden />
      {message}
    </p>
  );
}

function discoverStageLabel(stage: string | undefined): string {
  switch (stage) {
    case "discovery":
      return "Searching external sources…";
    case "ranking":
      return "Ranking candidates against the seed profile…";
    case "trail":
      return "Classifying relationships…";
    case "done":
      return "Done.";
    default:
      return "Starting…";
  }
}

const signalLabels: Record<string, string> = {
  semantic_doc: "semantic",
  semantic_chunk: "chunk sim",
  problem_sim: "problem",
  method_sim: "method",
  dataset_overlap: "dataset",
  citation: "citation",
  recency: "recency",
};

const citationRelationshipLabel: Record<CitationRelationship, string> = {
  cited_by_seed: "cited by seed",
  cites_seed: "cites seed",
  co_cited: "co-cited",
  none: "",
};

const BAND_FILTERS: { value: Confidence | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

const SORTS = [
  { value: "rank", label: "Rank" },
  { value: "semantic_doc", label: "Semantic" },
  { value: "citation", label: "Citation" },
  { value: "recency", label: "Recency" },
] as const;

export default function DiscoverPage() {
  return (
    <Suspense
      fallback={
        <PageShell>
          <SkeletonBlock className="h-80 w-full" />
        </PageShell>
      }
    >
      <DiscoverContent />
    </Suspense>
  );
}

function DiscoverContent() {
  const { seedId } = useParams<{ seedId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const runId = searchParams.get("run");
  const { ready } = useRequireAuth();

  const { data: seedPaper } = useSWR(ready ? ["paper", seedId] : null, () => papers.get(seedId));

  // Auto-start a run the moment this page is reached with no `run` in the
  // URL -- the researcher already made the decision by clicking "Start
  // discovery" on the seed page; a second confirmation click here would be
  // friction with no real purpose. The job id then lives in state only
  // until it resolves, at which point the URL itself gains `?run=...` so a
  // refresh or a shared link resumes the real result instead of starting a
  // fresh (billable) run.
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const startedRef = useRef(false);
  const polling = useJobPolling(jobId);

  useEffect(() => {
    if (!ready || runId || startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        const res = await papers.discoverRelated(seedId);
        setJobId(res.job.job_id);
      } catch (err) {
        if (err instanceof ApiError && err.code === "conflict") {
          setStartError("This paper needs a research profile first.");
        } else {
          setStartError(err instanceof ApiError ? err.message : "Could not start discovery.");
        }
      }
    })();
  }, [ready, runId, seedId]);

  useEffect(() => {
    if (!polling.isDone || !polling.job) return;
    const { status, result_ref } = polling.job;
    if ((status === "succeeded" || status === "partial") && result_ref) {
      router.replace(`/discover/${seedId}?run=${result_ref}`);
    }
  }, [polling.isDone, polling.job, seedId, router]);

  function retryDiscovery() {
    setStartError(null);
    startedRef.current = false;
    setJobId(null);
  }

  const {
    data: related,
    error: relatedError,
    isLoading: relatedLoading,
  } = useSWR(runId ? ["related", seedId, runId] : null, () => papers.related(seedId, runId as string));

  const [band, setBand] = useState<Confidence | "all">("all");
  const [sort, setSort] = useState<(typeof SORTS)[number]["value"]>("rank");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const dialogRef = useRef<CinematicDialogHandle>(null);
  const [workspaceTitle, setWorkspaceTitle] = useState("");
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function handleCreateWorkspace(): Promise<void> {
    setCreatingWorkspace(true);
    setCreateError(null);
    try {
      const ws = await workspaces.create({
        title: workspaceTitle.trim() || `${seedPaper?.title ?? "Untitled"} workspace`,
        seed_paper_id: seedId,
        import_run_id: runId ?? undefined,
      });
      if (selected.size > 0 && runId) {
        await workspaces.addPapers(ws.workspace_id, { paper_ids: Array.from(selected), from_run_id: runId });
      }
      dialogRef.current?.close();
      router.push(`/workspaces/${ws.workspace_id}`);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Could not create workspace.");
    } finally {
      setCreatingWorkspace(false);
    }
  }

  if (!ready) return null;

  const filteredResults = (related?.results ?? [])
    .filter((r) => band === "all" || r.band === band)
    .slice()
    .sort((a, b) => {
      if (sort === "rank") return (a.final_rank ?? 999) - (b.final_rank ?? 999);
      const av = a.signals?.[sort as keyof typeof a.signals] ?? -1;
      const bv = b.signals?.[sort as keyof typeof b.signals] ?? -1;
      return (bv ?? -1) - (av ?? -1);
    });

  return (
    <PageShell>
      <Reveal>
        <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-5" style={{ borderColor: C.lineStrong }}>
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wider" style={{ color: C.muted2 }}>
              Discovery for
            </p>
            <h1 className="mt-1 max-w-2xl truncate text-[clamp(20px,2.6vw,28px)] font-extrabold tracking-[-0.02em]">
              {seedPaper?.title ?? seedId}
            </h1>
          </div>
          <Link
            href={`/seed/${seedId}`}
            className="shrink-0 rounded-full px-4 py-2 text-sm font-semibold"
            style={{ background: "rgba(255,255,255,.05)", border: `1px solid ${C.lineStrong}` }}
          >
            Back to seed paper
          </Link>
        </div>
      </Reveal>

      {!runId && (
        <div className="mt-10">
          {startError ? (
            <Reveal>
              <div className="mx-auto max-w-md rounded-2xl px-6 py-12 text-center" style={{ background: C.glass, border: `1px dashed ${C.lineStrong}` }}>
                <p className="text-base font-semibold">Could not start discovery</p>
                <p className="mt-2 text-sm" style={{ color: C.muted }}>
                  {startError}
                </p>
                <button
                  type="button"
                  onClick={retryDiscovery}
                  className="mt-5 rounded-full px-5 py-2.5 text-sm font-semibold"
                  style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
                >
                  Try again
                </button>
              </div>
            </Reveal>
          ) : polling.job?.status === "failed" ? (
            <Reveal>
              <div className="mx-auto max-w-md rounded-2xl px-6 py-12 text-center" style={{ background: C.glass, border: `1px dashed ${C.lineStrong}` }}>
                <p className="text-base font-semibold">Discovery failed</p>
                <p className="mt-2 text-sm" style={{ color: C.muted }}>
                  Try again, or try a different seed paper.
                </p>
                <button
                  type="button"
                  onClick={retryDiscovery}
                  className="mt-5 rounded-full px-5 py-2.5 text-sm font-semibold"
                  style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
                >
                  Try again
                </button>
              </div>
            </Reveal>
          ) : (
            <Reveal>
              <div className="mx-auto max-w-md rounded-2xl px-6 py-14 text-center" style={{ background: C.glass, border: `1px solid ${C.line}` }}>
                <Compass className="mx-auto size-8 animate-pulse" style={{ color: C.mint }} aria-hidden />
                <p className="mt-4 text-base font-semibold" role="status" aria-live="polite">
                  {discoverStageLabel(polling.job?.progress.stage)}
                </p>
                <p className="mt-1.5 text-sm" style={{ color: C.muted }}>
                  Searching arXiv, OpenAlex, Semantic Scholar, and Crossref, then ranking against the seed profile.
                </p>
              </div>
            </Reveal>
          )}
        </div>
      )}

      {runId && relatedLoading && (
        <div className="mt-8 space-y-3">
          <SkeletonBlock className="h-24 w-full" />
          <SkeletonBlock className="h-24 w-full" />
          <SkeletonBlock className="h-24 w-full" />
        </div>
      )}

      {runId && relatedError && (
        <div className="mt-8">
          <InlineError
            message={relatedError instanceof ApiError ? relatedError.message : "Could not load related papers."}
          />
        </div>
      )}

      {runId && related && (
        <div className="mt-8">
          <Reveal>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4 text-sm" style={{ borderColor: C.line, color: C.muted }}>
              <span>
                {related.run.counts.after_filter} candidates from {related.run.strategies_succeeded.join(", ") || "no"} strategies
                {related.run.strategies_failed.length > 0 && ` · ${related.run.strategies_failed.join(", ")} failed`}
              </span>
              <details>
                <summary className="cursor-pointer" style={{ color: C.muted2 }}>
                  How this search ran
                </summary>
                <div className="mt-2 space-y-1 rounded-lg px-3 py-2 font-mono text-xs" style={{ background: "rgba(0,0,0,.3)" }}>
                  <p>found {related.run.counts.raw}</p>
                  <p>after dedupe {related.run.counts.after_dedupe}</p>
                  <p>after filter {related.run.counts.after_filter}</p>
                  <p>extra citation hop {related.run.extra_citation_hop_used ? "used" : "not used"}</p>
                </div>
              </details>
            </div>
          </Reveal>

          <Reveal delay={0.05}>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                {BAND_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    onClick={() => setBand(f.value)}
                    aria-pressed={band === f.value}
                    className="rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors"
                    style={
                      band === f.value
                        ? { color: C.mintInk, background: C.mint }
                        : { color: C.muted, background: "rgba(255,255,255,.04)", border: `1px solid ${C.line}` }
                    }
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <label className="inline-flex items-center gap-2 text-xs" style={{ color: C.muted }}>
                Sort by
                <span className="relative inline-flex items-center">
                  <select
                    value={sort}
                    onChange={(e) => setSort(e.target.value as typeof sort)}
                    className="appearance-none rounded-full py-1.5 pl-3 pr-7 text-xs font-medium"
                    style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.line}`, color: C.ink }}
                  >
                    {SORTS.map((s) => (
                      <option key={s.value} value={s.value} style={{ color: "#000" }}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  <CaretDown className="pointer-events-none absolute right-2 size-3" aria-hidden />
                </span>
              </label>
            </div>
          </Reveal>

          {filteredResults.length === 0 ? (
            <Reveal delay={0.1}>
              <div className="mt-6 rounded-2xl px-6 py-14 text-center" style={{ background: C.glass, border: `1px dashed ${C.lineStrong}` }}>
                <p className="text-base font-semibold">
                  {related.results.length === 0 ? "No related papers found" : "No results match this filter"}
                </p>
                <p className="mt-2 text-sm" style={{ color: C.muted }}>
                  {related.results.length === 0
                    ? "Try again later, or broaden the seed paper's profile."
                    : "Try a different confidence filter."}
                </p>
              </div>
            </Reveal>
          ) : (
            <ul className="mt-6 space-y-3">
              {filteredResults.map((r, i) => (
                <Reveal key={r.paper.id} delay={Math.min(i * 0.04, 0.3)}>
                  <ResultCard result={r} selected={selected.has(r.paper.id)} onToggle={() => toggleSelected(r.paper.id)} />
                </Reveal>
              ))}
            </ul>
          )}

          <div
            className="sticky bottom-4 mt-6 flex items-center justify-between gap-3 rounded-2xl px-5 py-3.5 backdrop-blur-[18px]"
            style={{ background: C.glass2, border: `1px solid ${C.lineStrong}`, boxShadow: "0 20px 50px -20px rgba(0,0,0,.7)" }}
          >
            <p className="text-sm" style={{ color: C.muted }}>
              {selected.size} selected
            </p>
            <button
              type="button"
              onClick={() => dialogRef.current?.show()}
              className="rounded-full px-5 py-2.5 text-sm font-semibold"
              style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
            >
              Create workspace{selected.size > 0 ? ` with ${selected.size} paper${selected.size === 1 ? "" : "s"}` : ""}
            </button>
          </div>
        </div>
      )}

      <CinematicDialog ref={dialogRef} title="Create a workspace" onClose={() => setCreateError(null)}>
        <div className="space-y-4">
          <div className="flex flex-col gap-1.5 text-left">
            <label htmlFor="workspace-title" className="text-sm font-medium">
              Title
            </label>
            <input
              id="workspace-title"
              type="text"
              placeholder={`${seedPaper?.title ?? ""} workspace`}
              value={workspaceTitle}
              onChange={(e) => setWorkspaceTitle(e.target.value)}
              className="h-10 rounded-xl px-3 text-sm outline-none transition-colors"
              style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
              onFocus={(e) => (e.currentTarget.style.borderColor = C.mint)}
              onBlur={(e) => (e.currentTarget.style.borderColor = C.lineStrong)}
            />
          </div>
          <p className="text-xs" style={{ color: C.muted }}>
            {selected.size > 0
              ? `${seedPaper?.title ?? "The seed paper"} plus ${selected.size} selected paper${selected.size === 1 ? "" : "s"} will be added, and their relationship to the seed will be filed as accepted on the trail.`
              : `Only ${seedPaper?.title ?? "the seed paper"} will be added. You can add more papers from the trail later.`}
          </p>
          {createError && <InlineError message={createError} />}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => dialogRef.current?.close()}
              className="rounded-full px-4 py-2 text-sm font-semibold"
              style={{ background: "rgba(255,255,255,.05)", border: `1px solid ${C.lineStrong}` }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreateWorkspace}
              disabled={creatingWorkspace}
              className="rounded-full px-4 py-2 text-sm font-semibold disabled:opacity-60"
              style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
            >
              {creatingWorkspace ? "Creating…" : "Create workspace"}
            </button>
          </div>
        </div>
      </CinematicDialog>
    </PageShell>
  );
}

function ResultCard({ result, selected, onToggle }: { result: RelatedResult; selected: boolean; onToggle: () => void }): ReactNode {
  const signalEntries = result.signals
    ? Object.entries(result.signals).filter((entry): entry is [string, number] => entry[1] != null)
    : [];
  const methods = [
    ...result.discovery_methods.map((m) => m.replace(/_/g, " ")),
    ...(result.citation_relationship !== "none" ? [citationRelationshipLabel[result.citation_relationship]] : []),
  ];

  return (
    <li>
      <div className="overflow-hidden rounded-2xl" style={{ background: C.glass, border: `1px solid ${C.line}` }}>
        <div className="flex gap-3 p-5">
          <button
            type="button"
            onClick={onToggle}
            aria-pressed={selected}
            aria-label={`Select ${result.paper.title}`}
            className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md transition-colors"
            style={
              selected
                ? { background: C.mint, color: C.mintInk }
                : { background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}` }
            }
          >
            {selected && <Check className="size-3.5" weight="bold" aria-hidden />}
          </button>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="min-w-0 text-sm font-semibold">{result.paper.title}</p>
              <span className="flex shrink-0 items-center gap-1.5 font-mono text-xs" style={{ color: C.muted2 }}>
                {result.final_rank != null && <span>#{result.final_rank}</span>}
                {result.band ? (
                  <span style={{ color: C.mint }}>
                    {result.band === "high" ? "●" : result.band === "medium" ? "◐" : "○"} {result.band}
                  </span>
                ) : (
                  <span>rank pending</span>
                )}
              </span>
            </div>
            <p className="text-xs" style={{ color: C.muted2 }}>
              {result.paper.authors.length > 0 ? result.paper.authors.join(", ") : "Authors unknown"}
              {result.paper.venue && ` · ${result.paper.venue}`}
              {result.paper.year != null && ` · ${result.paper.year}`}
            </p>

            {result.explanation?.prose && (
              <p className="text-sm" style={{ color: C.muted }}>
                {result.explanation.prose}
              </p>
            )}

            {signalEntries.length > 0 && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 border-y py-2 font-mono text-xs sm:grid-cols-3" style={{ borderColor: C.line, color: C.muted }}>
                {signalEntries.map(([name, value]) => (
                  <span key={name} className="flex items-baseline gap-1.5">
                    <span style={{ color: C.muted2 }}>{signalLabels[name] ?? name}</span>
                    <span>{value.toFixed(2)}</span>
                  </span>
                ))}
              </div>
            )}

            {result.explanation && result.explanation.bullet_reasons.length > 0 && (
              <details>
                <summary className="cursor-pointer text-xs" style={{ color: C.muted2 }}>
                  Why this rank
                </summary>
                <ul className="mt-1.5 list-inside list-disc space-y-0.5 rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(0,0,0,.3)", color: C.muted }}>
                  {result.explanation.bullet_reasons.map((reason, i) => (
                    <li key={i}>{reason}</li>
                  ))}
                </ul>
              </details>
            )}

            {(result.paper.doi || result.paper.url) && (
              <a
                href={result.paper.doi ? `https://doi.org/${result.paper.doi}` : result.paper.url!}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs transition-colors hover:text-white"
                style={{ color: C.mint }}
              >
                View source <ArrowSquareOut className="size-3" aria-hidden />
              </a>
            )}
          </div>
        </div>
        {methods.length > 0 && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 border-t px-5 py-2.5 font-mono text-[0.6875rem]" style={{ borderColor: C.line, color: C.muted2 }}>
            {methods.map((m) => (
              <span key={m}>→ {m}</span>
            ))}
          </div>
        )}
      </div>
    </li>
  );
}
