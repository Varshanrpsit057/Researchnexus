"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import useSWR, { useSWRConfig } from "swr";
import { Compass, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { jobs, papers, workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { useJobPolling } from "@/lib/api/hooks";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { CINEMATIC } from "@/lib/cinematic-theme";
import { STRATEGY_LABEL, discoveryProgress, runState } from "@/lib/discovery";
import { Reveal } from "@/components/effects/Reveal";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { CinematicDialog, type CinematicDialogHandle } from "@/components/ui/CinematicDialog";
import type { Job } from "@/lib/api/types";
import { RunProgress } from "./RunProgress";
import { RunReport } from "./RunReport";
import { Results } from "./Results";
import { readCriteria } from "@/lib/ranking";
import { readPublishers } from "@/lib/publishers";

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

function strategyNames(names: string[]): string {
  return names.map((n) => (STRATEGY_LABEL[n as keyof typeof STRATEGY_LABEL] ?? n.replace(/_/g, " ")).toLowerCase()).join(", ");
}

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
  // friction with no real purpose. The running job's id goes in the URL
  // (`?job=`) at once, so a refresh or a return visit follows the same run
  // (and the backend hands back a run of this seed already going rather
  // than start a second); once it finishes the URL gains `?run=...` so a
  // refresh or a shared link shows the real result.
  const jobId = runId ? null : searchParams.get("job");
  const [startError, setStartError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const startedRef = useRef(false);
  const polling = useJobPolling(jobId);
  const { mutate } = useSWRConfig();

  useEffect(() => {
    if (!ready || runId || jobId || startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        const res = await papers.discoverRelated(seedId, readCriteria(), [...readPublishers()]);
        router.replace(`/discover/${seedId}?job=${res.job.job_id}`);
      } catch (err) {
        if (err instanceof ApiError && err.code === "conflict") {
          setStartError("This paper needs a research profile first.");
        } else {
          setStartError(err instanceof ApiError ? err.message : "Could not start discovery.");
        }
      }
    })();
  }, [ready, runId, jobId, seedId, router]);

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
    router.replace(`/discover/${seedId}`);
  }

  async function cancelDiscovery() {
    if (!jobId) return;
    setCancelling(true);
    setCancelError(null);
    try {
      const job = await jobs.cancel(jobId);
      await mutate<Job>(["job", jobId], job, { revalidate: false });
    } catch (err) {
      setCancelError(err instanceof ApiError ? err.message : "Could not cancel discovery; it is still running.");
    } finally {
      setCancelling(false);
    }
  }

  const state = runState(polling.job);
  // a `?job=` link to a run that no longer exists
  const jobMissing = polling.error instanceof ApiError && polling.error.status === 404;

  const {
    data: related,
    error: relatedError,
    isLoading: relatedLoading,
  } = useSWR(runId ? ["related", seedId, runId] : null, () => papers.related(seedId, runId as string));

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
      router.push(`/workspace/${ws.workspace_id}`);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Could not create workspace.");
    } finally {
      setCreatingWorkspace(false);
    }
  }

  if (!ready) return null;

  return (
    <PageShell>
      <Reveal>
        <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-5" style={{ borderColor: C.lineStrong }}>
          <div className="min-w-0 max-w-4xl">
            <h1 className="text-[clamp(20px,2.4vw,28px)] font-extrabold leading-tight tracking-[-0.02em] [text-wrap:balance]">
              {seedPaper?.title ?? seedId}
            </h1>
            <p className="mt-1.5 text-sm" style={{ color: C.muted }}>
              Related work found from this paper
            </p>
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
          ) : jobMissing || state === "failed" || state === "interrupted" || state === "cancelled" ? (
            <Reveal>
              <div
                className="mx-auto max-w-md rounded-2xl px-6 py-12 text-center"
                style={{ background: C.glass, border: `1px dashed ${C.lineStrong}` }}
                data-testid="discovery-ended"
              >
                <p className="text-base font-semibold">
                  {jobMissing
                    ? "This discovery run can't be found"
                    : state === "cancelled"
                      ? "Discovery cancelled"
                      : state === "interrupted"
                        ? "Discovery was interrupted"
                        : "Discovery failed"}
                </p>
                <p className="mt-2 text-sm" style={{ color: C.muted }}>
                  {jobMissing
                    ? "It may have been removed. Start a new one to see this paper's related work."
                    : state === "cancelled"
                      ? "You stopped this run; nothing from it was saved."
                      : polling.job?.error ?? "Try again, or try a different seed paper."}
                </p>
                <button
                  type="button"
                  onClick={retryDiscovery}
                  className="mt-5 rounded-full px-5 py-2.5 text-sm font-semibold"
                  style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
                >
                  {state === "failed" && !jobMissing ? "Try again" : "Start again"}
                </button>
              </div>
            </Reveal>
          ) : jobId ? (
            <Reveal>
              <RunProgress
                progress={discoveryProgress(polling.job?.progress)}
                stage={polling.job?.progress.stage}
                onCancel={cancelDiscovery}
                cancelling={cancelling}
                cancelError={cancelError}
              />
            </Reveal>
          ) : (
            <Reveal>
              <div className="mx-auto max-w-md rounded-2xl px-6 py-14 text-center" style={{ background: C.glass, border: `1px solid ${C.line}` }}>
                <Compass className="mx-auto size-8 motion-safe:animate-pulse" style={{ color: C.mint }} aria-hidden />
                <p className="mt-4 text-base font-semibold" role="status" aria-live="polite">
                  Starting…
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
        <div className="mt-4">
          <Reveal>
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm" style={{ borderColor: C.line, color: C.muted }}>
              <span>
                {related.run.counts.after_filter} candidates from {strategyNames(related.run.strategies_succeeded) || "no strategies"}
                {related.run.strategies_failed.length > 0 && ` · ${strategyNames(related.run.strategies_failed)} failed`}
                {(related.run.counts.off_topic ?? 0) > 0 && ` · ${related.run.counts.off_topic} off-topic set aside`}
              </span>
            </div>
            <RunReport run={related.run} />
          </Reveal>

          <Results
            seedId={seedId}
            runId={runId}
            related={related}
            selected={selected}
            onToggle={toggleSelected}
            onReranked={(next) => mutate(["related", seedId, runId], next, { revalidate: false })}
            onCreateWorkspace={() => dialogRef.current?.show()}
          />


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
              : `Only ${seedPaper?.title ?? "the seed paper"} will be added. You can add more of these results later, from the workspace page.`}
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
