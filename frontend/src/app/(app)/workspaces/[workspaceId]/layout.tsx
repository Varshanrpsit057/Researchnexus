"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import useSWR from "swr";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { ErrorState, Skeleton } from "@/components/ui/States";

/** Guide-card groups, not a ten-item peer row: the workspace's own real
 * structure (what it holds / how those items relate / what synthesis is run
 * over them / what happened) organizes the rail the way section breaks
 * organize a drawer of index cards, each group's own small label card. */
const GROUPS: { label: string; tabs: { slug: string; label: string }[] }[] = [
  {
    label: "Record",
    tabs: [
      { slug: "", label: "Overview" },
      { slug: "papers", label: "Papers" },
      { slug: "citations", label: "Citations" },
    ],
  },
  {
    label: "Relationships",
    tabs: [
      { slug: "trail", label: "Trail" },
      { slug: "graph", label: "Graph" },
    ],
  },
  {
    label: "Synthesis",
    tabs: [
      { slug: "chat", label: "Chat" },
      { slug: "compare", label: "Compare" },
      { slug: "gaps", label: "Gaps" },
      { slug: "directions", label: "Directions" },
    ],
  },
  {
    label: "Log",
    tabs: [{ slug: "activity", label: "Activity" }],
  },
];

export function useWorkspace(workspaceId: string) {
  return useSWR(["workspace", workspaceId], () => workspaces.get(workspaceId));
}

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const { data: workspace, error, isLoading, mutate } = useWorkspace(workspaceId);
  const basePath = `/workspaces/${workspaceId}`;

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !workspace) {
    return (
      <ErrorState
        title={error instanceof ApiError && error.status === 404 ? "Workspace not found" : "Could not load workspace"}
        description={error instanceof ApiError ? error.message : undefined}
        onRetry={() => mutate()}
      />
    );
  }

  const budgetFraction = workspace.token_budget_usd > 0 ? Math.min(1, workspace.cost_used_usd / workspace.token_budget_usd) : 0;
  const currentSlug = pathname === basePath ? "" : (pathname.slice(basePath.length + 1).split("/")[0] ?? "");

  return (
    <div className="space-y-6">
      {/* The drawer's own face: title as its outer label, budget as a
          ruled gauge rather than a soft progress pill. */}
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border-strong pb-4">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold tracking-tightest text-ink">{workspace.title}</h1>
          <p className="mt-1 font-mono text-xs text-ink-subtle">
            {workspace.workspace_id} · seed {workspace.seed_paper_id}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-xs text-ink-muted">
            ${workspace.cost_used_usd.toFixed(3)} / ${workspace.token_budget_usd.toFixed(2)} spent
          </p>
          <div
            className="relative mt-1.5 h-2 w-32 overflow-hidden bg-[repeating-linear-gradient(90deg,var(--border-strong)_0,var(--border-strong)_1px,transparent_1px,transparent_8px)]"
            role="progressbar"
            aria-valuenow={Math.round(budgetFraction * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Budget spent"
          >
            <div className="absolute inset-y-0 left-0 bg-accent" style={{ width: `${budgetFraction * 100}%` }} />
          </div>
        </div>
      </header>

      {/* Mobile / narrow: a native select stands in for the rail -- the
          most standard control for jumping to one of many sections, not a
          horizontal scroll of ten tabs. */}
      <label className="block lg:hidden">
        <span className="sr-only">Workspace section</span>
        <select
          value={currentSlug}
          onChange={(e) => router.push(e.target.value ? `${basePath}/${e.target.value}` : basePath)}
          className="h-10 w-full rounded-sm border border-border-strong bg-surface-raised px-3 text-sm font-medium text-ink"
        >
          {GROUPS.map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.tabs.map((tab) => (
                <option key={tab.slug} value={tab.slug}>
                  {tab.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>

      <div className="lg:grid lg:grid-cols-[184px_1fr] lg:items-start lg:gap-10">
        <nav aria-label="Workspace sections" className="hidden lg:block lg:sticky lg:top-6 lg:-mx-3 lg:bg-surface-sunken lg:py-4">
          <ul className="space-y-5">
            {GROUPS.map((group) => (
              <li key={group.label}>
                <p className="mb-1 px-4 font-mono text-[0.6875rem] uppercase tracking-wider text-ink-subtle">{group.label}</p>
                <ul>
                  {group.tabs.map((tab) => {
                    const href = tab.slug ? `${basePath}/${tab.slug}` : basePath;
                    const active = pathname === href;
                    return (
                      <li key={tab.slug || "overview"}>
                        <Link
                          href={href}
                          aria-current={active ? "page" : undefined}
                          className={`block py-1.5 pr-3 text-sm transition-colors ${
                            active
                              ? "bg-surface pl-5 font-semibold text-ink"
                              : "pl-4 font-medium text-ink-muted hover:bg-surface/60 hover:text-ink"
                          }`}
                        >
                          {tab.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
