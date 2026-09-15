"use client";

import Link from "next/link";
import { ArrowRight } from "@phosphor-icons/react/dist/ssr";
import { useParams } from "next/navigation";
import { useWorkspace } from "./layout";
import { Card, CardHeader } from "@/components/ui/Card";

const QUICK_LINKS: { slug: string; label: string; description: string }[] = [
  { slug: "trail", label: "Typed research trail", description: "Review how each related paper connects to the seed." },
  { slug: "chat", label: "Chat", description: "Ask questions answered from this workspace's papers, with citations." },
  { slug: "compare", label: "Compare", description: "See how the workspace papers differ side by side." },
  { slug: "gaps", label: "Research gaps", description: "Evidence-grounded gaps across the workspace papers." },
];

export default function WorkspaceOverviewPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { data: workspace } = useWorkspace(workspaceId);
  if (!workspace) return null;

  const stats: { label: string; value: number }[] = [
    { label: "papers", value: workspace.counts?.papers ?? workspace.papers.length },
    { label: "trail edges", value: workspace.counts?.edges ?? 0 },
    { label: "gaps", value: workspace.counts?.gaps ?? 0 },
    { label: "directions", value: workspace.counts?.directions ?? 0 },
  ];

  return (
    <div className="space-y-8">
      {/* One ledger line, not four stat tiles: the tally you'd find
          pencilled at the bottom of a drawer's own count card. */}
      <div className="flex flex-wrap gap-x-6 gap-y-2 divide-x divide-border border-y border-border py-3 font-mono text-sm">
        {stats.map((s, i) => (
          <span key={s.label} className={i > 0 ? "pl-6" : ""}>
            <span className="font-semibold text-ink">{s.value}</span> <span className="text-ink-subtle">{s.label}</span>
          </span>
        ))}
      </div>

      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-ink">Papers in this workspace</h2>
        </CardHeader>
        <ul className="divide-y divide-border">
          {workspace.papers.map((p) => (
            <li key={p.paper_id} className="flex items-center justify-between gap-3 px-4 py-3">
              <Link href={`/papers/${p.paper_id}`} className="min-w-0 truncate text-sm text-ink hover:underline">
                {p.paper_id}
              </Link>
              <div className="flex shrink-0 items-center gap-3 text-xs text-ink-subtle">
                <span>{p.role}</span>
                {p.ranking_snapshot && <span className="font-mono">rank {p.ranking_snapshot.final_rank}</span>}
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <div>
        <h2 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink-subtle">Go to</h2>
        <ul className="divide-y divide-border border-y border-border">
          {QUICK_LINKS.map((link) => (
            <li key={link.slug}>
              <Link
                href={`/workspaces/${workspaceId}/${link.slug}`}
                className="group flex items-center justify-between gap-4 py-4 transition-colors hover:bg-surface-sunken"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{link.label}</p>
                  <p className="mt-0.5 text-xs text-ink-muted">{link.description}</p>
                </div>
                <ArrowRight className="size-4 shrink-0 text-ink-subtle transition-transform group-hover:translate-x-0.5" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
