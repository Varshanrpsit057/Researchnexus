"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Check, Sparkle, X } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import { useJobPolling } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import type { GapUserState, ResearchGap } from "@/lib/api/types";
import { Card, CardBody, CardTracings } from "@/components/ui/Card";
import { ConfidenceBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfidenceBasisDisclosure } from "@/components/ui/ConfidenceBasis";
import { EmptyState, ErrorState, InlineError, Skeleton } from "@/components/ui/States";

const FILTERS: { value: GapUserState; label: string }[] = [
  { value: "candidate", label: "Candidates" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
];

export default function WorkspaceGapsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [filter, setFilter] = useState<GapUserState>("candidate");
  const { data, error, isLoading, mutate } = useSWR(["gaps", workspaceId, filter], () => workspaces.listGaps(workspaceId, filter));

  const [jobId, setJobId] = useState<string | null>(null);
  const [genError, setGenError] = useState<string | null>(null);
  const polling = useJobPolling(jobId);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const allSelected = !!data && data.gaps.length > 0 && data.gaps.every((g) => selected.has(g.gap_id));

  // Once the job reaches a terminal status SWR's own refreshInterval goes to
  // 0 (see useJobPolling), so this only re-runs once per completed job --
  // no need to null jobId back out afterward (that would be a setState call
  // in an effect body with nothing to synchronize it against).
  useEffect(() => {
    if (polling.isDone && jobId) mutate();
  }, [polling.isDone, jobId, mutate]);

  async function generate() {
    setGenError(null);
    try {
      const res = await workspaces.generateGaps(workspaceId, {});
      setJobId(res.job.job_id);
    } catch (err) {
      if (err instanceof ApiError && err.code === "llm_key_required") {
        setGenError("No working LLM provider key is saved yet. Add one in Settings, then generate gaps again.");
      } else {
        setGenError(err instanceof ApiError ? err.message : "Could not generate gaps.");
      }
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (!data) return;
    setSelected(allSelected ? new Set() : new Set(data.gaps.map((g) => g.gap_id)));
  }

  async function bulkSetState(state: GapUserState) {
    setBulkBusy(true);
    try {
      await Promise.all([...selected].map((id) => workspaces.setGapState(workspaceId, id, state)));
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
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => {
                setFilter(f.value);
                setSelected(new Set());
              }}
              aria-pressed={filter === f.value}
              className={`border-b-2 pb-1 font-medium transition-colors ${
                filter === f.value ? "border-accent text-ink" : "border-transparent text-ink-muted hover:text-ink"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <Button size="sm" variant="secondary" onClick={generate} loading={jobId != null && !polling.isDone}>
          <Sparkle className="size-4" aria-hidden />
          Generate gaps
        </Button>
      </div>
      {genError && <InlineError message={genError} />}
      {jobId && !polling.isDone && (
        <p className="text-sm text-ink-muted" role="status" aria-live="polite">
          Generating gaps from this workspace&apos;s papers&hellip; this can take a minute.
        </p>
      )}
      {polling.job?.status === "failed" && (
        <div className="space-y-1">
          <InlineError message="Gap generation failed. Try again." />
          {polling.job.error && (
            <details>
              <summary className="cursor-pointer list-none text-xs text-ink-subtle hover:text-ink-muted">Technical details</summary>
              <p className="rule-t mt-1 bg-surface-sunken px-2.5 py-1.5 font-mono text-[0.6875rem] text-ink-subtle">
                {polling.job.error}
              </p>
            </details>
          )}
        </div>
      )}

      {isLoading && <Skeleton className="h-40 w-full" />}
      {error && <ErrorState description={error instanceof ApiError ? error.message : undefined} onRetry={() => mutate()} />}

      {data && data.gaps.length === 0 && (
        <EmptyState title={`No ${filter} gaps`} description="Generate gaps from this workspace's papers, or check another filter." />
      )}

      {data && data.gaps.length > 0 && (
        <>
          <label className="flex items-center gap-1.5 text-xs font-medium text-ink-muted">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} className="accent-[var(--color-accent)]" />
            Select all ({data.gaps.length})
          </label>
          <ul className="space-y-3">
            {data.gaps.map((gap) => (
              <GapCard
                key={gap.gap_id}
                gap={gap}
                workspaceId={workspaceId}
                onChanged={() => mutate()}
                checked={selected.has(gap.gap_id)}
                onToggle={() => toggle(gap.gap_id)}
              />
            ))}
          </ul>
        </>
      )}

      {selected.size > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border-strong bg-surface-raised px-4 py-3 shadow-[0_-4px_16px_rgb(var(--shadow-color)/0.12)]">
          <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-3">
            <p className="text-sm font-medium text-ink">{selected.size} gap{selected.size === 1 ? "" : "s"} selected</p>
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

function GapCard({
  gap,
  workspaceId,
  onChanged,
  checked,
  onToggle,
}: {
  gap: ResearchGap;
  workspaceId: string;
  onChanged: () => void;
  checked: boolean;
  onToggle: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [justFiled, setJustFiled] = useState(false);
  const withdrawn = gap.user_state === "rejected";

  async function setState(state: GapUserState) {
    setBusy(true);
    try {
      await workspaces.setGapState(workspaceId, gap.gap_id, state);
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
        aria-label={`Select gap: ${gap.statement}`}
        className="mt-4 size-4 shrink-0 accent-[var(--color-accent)]"
      />
      <Card className="flex-1">
        <CardBody className="space-y-2">
          <div className={`flex flex-wrap items-start justify-between gap-2 ${withdrawn ? "stamp-withdrawn text-ink-subtle" : ""} ${justFiled ? "tracing-filed" : ""}`}>
            <p className="text-sm font-medium text-ink">{gap.statement}</p>
            <ConfidenceBadge confidence={gap.confidence} />
          </div>
          <p className="text-xs text-ink-subtle">
            {gap.gap_type.replace(/_/g, " ")} · {gap.supporting_papers.length} supporting paper{gap.supporting_papers.length === 1 ? "" : "s"} ·{" "}
            {Math.round(gap.evidence_coverage * 100)}% coverage ·{" "}
            <span className={gap.self_support_passed ? "text-verified" : "text-warning"}>
              self-support {gap.self_support_passed ? "passed" : "failed"}
            </span>
          </p>
          <p className="text-sm text-ink-muted">{gap.why_unaddressed}</p>
          <p className="text-sm text-ink-muted">
            <span className="font-medium text-ink">Proposed direction: </span>
            {gap.proposed_direction}
          </p>
          {gap.novelty_assessment && (
            <p className="text-sm text-ink-muted">
              <span className="font-medium text-ink">Novelty: </span>
              {gap.novelty_assessment}
            </p>
          )}
          <p className="font-mono text-xs text-ink-subtle">detection rule: {gap.detection_rule}</p>

          {gap.supporting_evidence.length > 0 && (
            <details>
              <summary className="cursor-pointer list-none text-xs text-ink-subtle hover:text-ink-muted">
                {gap.supporting_evidence.length} evidence span{gap.supporting_evidence.length === 1 ? "" : "s"}
              </summary>
              <ul className="mt-1 space-y-1">
                {gap.supporting_evidence.map((ev, i) => (
                  <li key={i} className="rule-t bg-surface-sunken px-2.5 py-1.5 text-xs italic text-ink-muted">
                    &ldquo;{ev.span.quote}&rdquo; <span className="not-italic text-ink-subtle">({ev.paper_id})</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <ConfidenceBasisDisclosure basis={gap.confidence_basis} />
        </CardBody>
        <CardTracings entries={gap.supporting_papers.map((id) => ({ label: id, href: `/papers/${id}` }))} />
        <div className="rule-t flex items-center justify-between px-4 py-2">
          <span className="font-mono text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
            {withdrawn ? "withdrawn" : gap.user_state}
          </span>
          <div className="flex items-center gap-4">
            <Button size="sm" variant="ghost" disabled={busy || withdrawn} onClick={() => setState("rejected")}>
              <X className="size-3.5" aria-hidden />
              Reject
            </Button>
            <Button size="sm" variant="secondary" disabled={busy || gap.user_state === "accepted"} onClick={() => setState("accepted")}>
              <Check className="size-3.5" aria-hidden />
              Accept
            </Button>
          </div>
        </div>
      </Card>
    </li>
  );
}
