"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { Check, Quotes, X } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { EdgeUserState, RelationshipType, TrailGroupEntry } from "@/lib/api/types";
import { RELATIONSHIP_TYPES } from "@/lib/api/types";
import { Card, CardBody, CardTracings } from "@/components/ui/Card";
import { ConfidenceBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfidenceBasisDisclosure } from "@/components/ui/ConfidenceBasis";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";

const STATE_FILTERS: { value: string | undefined; label: string }[] = [
  { value: undefined, label: "Pending + accepted" },
  { value: "pending", label: "Pending" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
];

export default function WorkspaceTrailPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [stateFilter, setStateFilter] = useState<string | undefined>(undefined);
  const { data, error, isLoading, mutate } = useSWR(
    ["trail", workspaceId, stateFilter],
    () => workspaces.trail(workspaceId, stateFilter ? { state: stateFilter } : undefined)
  );

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const visibleEdgeIds = data
    ? RELATIONSHIP_TYPES.flatMap((t) => (data.groups[t] ?? []).map((e) => e.edge.edge_id))
    : [];
  const allVisibleSelected = visibleEdgeIds.length > 0 && visibleEdgeIds.every((id) => selected.has(id));

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllVisible() {
    setSelected((prev) => {
      if (allVisibleSelected) return new Set([...prev].filter((id) => !visibleEdgeIds.includes(id)));
      return new Set([...prev, ...visibleEdgeIds]);
    });
  }

  async function bulkSetState(state: EdgeUserState) {
    setBulkBusy(true);
    try {
      await Promise.all([...selected].map((id) => workspaces.setEdgeState(workspaceId, id, state)));
      setSelected(new Set());
      await mutate();
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <div className="space-y-5 pb-16">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div className="flex flex-wrap gap-4 text-sm">
          {STATE_FILTERS.map((f) => (
            <button
              key={f.label}
              type="button"
              onClick={() => {
                setStateFilter(f.value);
                setSelected(new Set());
              }}
              aria-pressed={stateFilter === f.value}
              className={`border-b-2 pb-1 font-medium transition-colors ${
                stateFilter === f.value
                  ? "border-accent text-ink"
                  : "border-transparent text-ink-muted hover:text-ink"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        {visibleEdgeIds.length > 0 && (
          <label className="flex items-center gap-1.5 text-xs font-medium text-ink-muted">
            <input type="checkbox" checked={allVisibleSelected} onChange={toggleAllVisible} className="accent-[var(--color-accent)]" />
            Select all visible ({visibleEdgeIds.length})
          </label>
        )}
      </div>

      {isLoading && <Skeleton className="h-64 w-full" />}
      {error && (
        <ErrorState description={error instanceof ApiError ? error.message : undefined} onRetry={() => mutate()} />
      )}

      {data && (
        <div className="space-y-7">
          {RELATIONSHIP_TYPES.map((type) => {
            const entries = data.groups[type] ?? [];
            if (entries.length === 0) return null;
            return (
              <TrailGroup
                key={type}
                type={type}
                entries={entries}
                workspaceId={workspaceId}
                onChanged={() => mutate()}
                selected={selected}
                onToggle={toggle}
              />
            );
          })}
          {RELATIONSHIP_TYPES.every((t) => (data.groups[t] ?? []).length === 0) && (
            <EmptyState
              title={stateFilter ? `No ${stateFilter} edges` : "No trail edges to show"}
              description={
                stateFilter
                  ? "Try another filter above."
                  : "Discover related papers from the seed paper, then create or refresh this workspace from those results."
              }
            />
          )}
        </div>
      )}

      {selected.size > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border-strong bg-surface-raised px-4 py-3 shadow-[0_-4px_16px_rgb(var(--shadow-color)/0.12)]">
          <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-3">
            <p className="text-sm font-medium text-ink">{selected.size} edge{selected.size === 1 ? "" : "s"} selected</p>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" disabled={bulkBusy} onClick={() => setSelected(new Set())}>
                Clear
              </Button>
              <Button size="sm" variant="ghost" disabled={bulkBusy} onClick={() => bulkSetState("rejected")} loading={bulkBusy}>
                <X className="size-3.5" aria-hidden />
                Reject {selected.size}
              </Button>
              <Button size="sm" variant="secondary" disabled={bulkBusy} onClick={() => bulkSetState("accepted")} loading={bulkBusy}>
                <Check className="size-3.5" aria-hidden />
                Accept {selected.size}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TrailGroup({
  type,
  entries,
  workspaceId,
  onChanged,
  selected,
  onToggle,
}: {
  type: RelationshipType;
  entries: TrailGroupEntry[];
  workspaceId: string;
  onChanged: () => void;
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-subtle">
        {type.replace(/_/g, " ")} <span className="text-ink-subtle">({entries.length})</span>
      </h2>
      <ul className="space-y-2">
        {entries.map((entry) => (
          <TrailEdgeRow
            key={entry.edge.edge_id}
            entry={entry}
            workspaceId={workspaceId}
            onChanged={onChanged}
            checked={selected.has(entry.edge.edge_id)}
            onToggle={() => onToggle(entry.edge.edge_id)}
          />
        ))}
      </ul>
    </div>
  );
}

function TrailEdgeRow({
  entry,
  workspaceId,
  onChanged,
  checked,
  onToggle,
}: {
  entry: TrailGroupEntry;
  workspaceId: string;
  onChanged: () => void;
  checked: boolean;
  onToggle: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [justFiled, setJustFiled] = useState(false);
  const { target, edge } = entry;
  const withdrawn = edge.user_state === "rejected";

  async function setState(state: EdgeUserState) {
    setBusy(true);
    try {
      await workspaces.setEdgeState(workspaceId, edge.edge_id, state);
      if (state === "accepted") setJustFiled(true);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex gap-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        aria-label={`Select ${target.title ?? target.id}`}
        className="mt-4 size-4 shrink-0 accent-[var(--color-accent)]"
      />
      <Card className="flex-1">
        <CardBody className="space-y-1.5">
          <div
            className={`flex flex-wrap items-start justify-between gap-2 ${withdrawn ? "stamp-withdrawn text-ink-subtle" : ""} ${justFiled ? "tracing-filed" : ""}`}
          >
            <div className="min-w-0">
              <Link href={`/papers/${target.id}`} className="text-sm font-medium text-ink hover:underline">
                {target.title ?? target.id}
              </Link>
              {target.year != null && <span className="ml-1.5 text-xs text-ink-subtle">{target.year}</span>}
            </div>
            <ConfidenceBadge confidence={edge.confidence} />
          </div>

          <p className="text-xs text-ink-subtle">
            {edge.detection_method.replace(/_/g, " ")}
            {edge.rule_fired && ` · rule: ${edge.rule_fired}`}
          </p>

          {edge.evidence.length > 0 && (
            <details>
              <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-ink-subtle hover:text-ink-muted">
                <Quotes className="size-3" aria-hidden />
                {edge.evidence.length} evidence span{edge.evidence.length === 1 ? "" : "s"}
              </summary>
              <ul className="mt-1 space-y-1">
                {edge.evidence.map((ev, i) => (
                  <li key={i} className="rule-t bg-surface-sunken px-2.5 py-1.5 text-xs italic text-ink-muted">
                    &ldquo;{ev.span.quote}&rdquo;
                    <span className="ml-1.5 not-italic text-ink-subtle">{ev.role}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <ConfidenceBasisDisclosure basis={edge.confidence_basis} />
        </CardBody>
        <CardTracings entries={edge.supporting_references.map((r) => ({ label: r }))} />
        <div className="rule-t flex items-center justify-between px-4 py-2">
          <span className="font-mono text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
            {withdrawn ? "withdrawn" : edge.user_state}
          </span>
          <div className="flex items-center gap-4">
            <Button size="sm" variant="ghost" disabled={busy || withdrawn} onClick={() => setState("rejected")}>
              <X className="size-3.5" aria-hidden />
              Reject
            </Button>
            <Button size="sm" variant="secondary" disabled={busy || edge.user_state === "accepted"} onClick={() => setState("accepted")}>
              <Check className="size-3.5" aria-hidden />
              Accept
            </Button>
          </div>
        </div>
      </Card>
    </li>
  );
}
