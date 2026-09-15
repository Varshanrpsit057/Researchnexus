"use client";

import Link from "next/link";
import useSWR from "swr";
import { Stack } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { Button } from "@/components/ui/Button";

export default function WorkspacesPage() {
  const { data, error, isLoading, mutate } = useSWR("workspaces", () => workspaces.list());

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 border-b border-border-strong pb-4">
        <h1 className="text-xl font-semibold tracking-tightest text-ink">Workspaces</h1>
        <p className="mt-1 text-sm text-ink-muted">
          A workspace groups a seed paper with the related work you&apos;ve accepted, for RAG chat, comparison, and gap analysis.
        </p>
      </div>

      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {error && (
        <ErrorState description={error instanceof ApiError ? error.message : undefined} onRetry={() => mutate()} />
      )}

      {data && data.workspaces.length === 0 && (
        <EmptyState
          icon={<Stack className="size-6" aria-hidden />}
          title="No workspaces yet"
          description="Discover related papers from a seed paper, then create a workspace from the results you want to keep."
          action={
            <Link href="/papers">
              <Button size="sm" variant="secondary">
                Start from a paper
              </Button>
            </Link>
          }
        />
      )}

      {data && data.workspaces.length > 0 && (
        <ul className="divide-y divide-border border-y border-border">
          {data.workspaces.map((ws) => (
            <li key={ws.workspace_id}>
              <Link
                href={`/workspaces/${ws.workspace_id}`}
                className="flex items-center justify-between gap-4 py-4 transition-colors hover:bg-surface-sunken"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink" title={ws.title}>{ws.title}</p>
                  <p className="mt-0.5 font-mono text-xs text-ink-subtle">{ws.workspace_id}</p>
                </div>
                <div className="flex shrink-0 items-center gap-4 text-right font-mono text-xs text-ink-subtle">
                  <span>{ws.counts?.papers ?? ws.papers.length} papers</span>
                  <span>
                    ${ws.cost_used_usd.toFixed(2)} / ${ws.token_budget_usd.toFixed(2)}
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
