"use client";

import { useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { FileText } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { CoverageState } from "@/lib/api/types";
import { coverageShort } from "@/lib/coverage";
import { C, focusRing, quietButton } from "./ui";

const ORDER: CoverageState[] = ["full_text", "abstract_only", "retrieval_failed", "no_text"];

/**
 * What text the workspace's papers are read from, and the way to get more
 * (remediation Phase 7). Papers joining the workspace are looked for by
 * themselves; this shows that run as it goes, and can start another.
 */
export function CoverageSummary({ workspaceId, paperCount }: { workspaceId: string; paperCount: number }) {
  const { mutate } = useSWRConfig();
  // a run this page saw in progress: when it ends, what it found is shown everywhere
  const watching = useRef<string | null>(null);
  const q = useSWR(["ws-coverage", workspaceId, paperCount], () => workspaces.coverage(workspaceId), {
    refreshInterval: (data) => (data?.job && (data.job.status === "queued" || data.job.status === "running") ? 2000 : 0),
    onSuccess: (data) => {
      const job = data.job;
      if (!job) return;
      if (job.status === "queued" || job.status === "running") {
        watching.current = job.job_id;
      } else if (watching.current === job.job_id) {
        watching.current = null;
        void mutate((key) => Array.isArray(key) && key[0] === "paper");
        void mutate(["workspace", workspaceId]);
      }
    },
  });
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const data = q.data;
  if (!data || data.papers.length === 0) return null;

  const running = data.job && (data.job.status === "queued" || data.job.status === "running");
  const missing = data.papers.filter((p) => p.coverage.state !== "full_text" && p.coverage.retrievable).length;
  const counts = ORDER.filter((s) => data.summary[s] > 0).map((s) => `${data.summary[s]} ${coverageShort(s)}`);
  const progress = data.job?.progress ?? {};

  async function start() {
    setStarting(true);
    setError(null);
    try {
      await workspaces.retrieveFullText(workspaceId);
      await q.mutate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't start. Try again.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-[13.5px]" data-testid="workspace-coverage">
      <p className="flex items-center gap-1.5" style={{ color: C.muted }}>
        <FileText className="size-4 shrink-0" aria-hidden />
        <span className="tabular-nums">{counts.join(" · ")}</span>
      </p>
      {running ? (
        <p role="status" className="tabular-nums" style={{ color: C.mint }}>
          Looking for full text
          {progress.total ? `: ${progress.done ?? 0} of ${progress.total} checked${progress.retrieved ? `, ${progress.retrieved} found` : ""}` : "…"}
        </p>
      ) : missing > 0 ? (
        <button
          type="button"
          onClick={start}
          disabled={starting}
          className={`inline-flex min-h-9 items-center rounded-full px-4 text-[13px] font-semibold transition-colors hover:bg-white/10 disabled:opacity-60 ${focusRing}`}
          style={{ ...quietButton, color: C.ink }}
        >
          {starting ? "Starting…" : `Look for full text (${missing} ${missing === 1 ? "paper" : "papers"})`}
        </button>
      ) : null}
      {error && (
        <p role="alert" className="w-full" style={{ color: C.danger }}>
          {error}
        </p>
      )}
    </div>
  );
}
