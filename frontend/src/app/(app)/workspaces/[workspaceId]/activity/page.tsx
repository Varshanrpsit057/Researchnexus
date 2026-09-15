"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { StageName } from "@/lib/api/types";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody } from "@/components/ui/Card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";

const STAGES: StageName[] = [
  "ingest", "profile", "discovery", "ranking", "trail", "workspace", "rag", "comparison", "gaps", "directions", "citations",
];

export default function WorkspaceActivityPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [stage, setStage] = useState<StageName | "">("");
  const { data, error, isLoading, mutate } = useSWR(
    ["activity", workspaceId, stage],
    () => workspaces.activity(workspaceId, stage ? { stage } : undefined)
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <label htmlFor="stage-filter" className="text-sm font-medium text-ink">
          Stage
        </label>
        <select
          id="stage-filter"
          value={stage}
          onChange={(e) => setStage(e.target.value as StageName | "")}
          className="h-9 rounded-sm border border-border-strong bg-surface-raised px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
        >
          <option value="">All stages</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {isLoading && <Skeleton className="h-64 w-full" />}
      {error && <ErrorState description={error instanceof ApiError ? error.message : undefined} onRetry={() => mutate()} />}
      {data && data.stage_runs.length === 0 && <EmptyState title="No activity recorded yet" description="Runs of chat, gaps, directions, and other stages will appear here." />}

      {data && data.stage_runs.length > 0 && (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border-strong text-left">
                  <th className="px-4 py-2 font-medium text-ink-muted">Stage</th>
                  <th className="px-4 py-2 font-medium text-ink-muted">Tool</th>
                  <th className="px-4 py-2 font-medium text-ink-muted">Status</th>
                  <th className="px-4 py-2 font-medium text-ink-muted">Tokens</th>
                  <th className="px-4 py-2 font-medium text-ink-muted">Cost</th>
                  <th className="px-4 py-2 font-medium text-ink-muted">Latency</th>
                  <th className="px-4 py-2 font-medium text-ink-muted">When</th>
                </tr>
              </thead>
              <tbody>
                {data.stage_runs.map((run) => (
                  <tr key={run.id} className="border-b border-border">
                    <td className="px-4 py-2">
                      <Badge>{run.stage}</Badge>
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-ink-subtle">{run.tool}</td>
                    <td className="px-4 py-2">
                      <Badge tone={run.ok ? "verified" : "danger"}>{run.ok ? "ok" : "error"}</Badge>
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-ink-muted">
                      {run.tokens_prompt}/{run.tokens_completion}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-ink-muted">${run.cost_usd.toFixed(4)}</td>
                    <td className="px-4 py-2 font-mono text-xs text-ink-muted">{run.latency_ms}ms</td>
                    <td className="px-4 py-2 text-xs text-ink-subtle">{new Date(run.ts).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.stage_runs.some((r) => r.error) && (
            <CardBody className="rule-t space-y-1">
              {data.stage_runs
                .filter((r) => r.error)
                .map((r) => (
                  <p key={r.id} className="text-xs text-danger">
                    {r.stage}: {r.error}
                  </p>
                ))}
            </CardBody>
          )}
        </Card>
      )}
    </div>
  );
}
