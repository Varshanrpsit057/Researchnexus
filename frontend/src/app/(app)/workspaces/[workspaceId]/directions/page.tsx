"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Check, Sparkle, X } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { DirectionsGenerateResponse, DirectionUserState, ResearchDirection } from "@/lib/api/types";
import { Card, CardBody, CardTracings } from "@/components/ui/Card";
import { ConfidenceBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfidenceBasisDisclosure, LeaderRow } from "@/components/ui/ConfidenceBasis";
import { EmptyState, ErrorState, InlineError, Skeleton } from "@/components/ui/States";

const STATE_FILTERS: { value: DirectionUserState | undefined; label: string }[] = [
  { value: undefined, label: "All" },
  { value: "candidate", label: "Candidates" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
];


function summarizeGeneration(res: DirectionsGenerateResponse): string {
  const parts = [`Generated ${res.generated} of ${res.requested} requested.`];
  if (res.dropped_unsupported > 0) {
    parts.push(`${res.dropped_unsupported} proposed direction${res.dropped_unsupported === 1 ? "" : "s"} lacked sufficient evidence and ${res.dropped_unsupported === 1 ? "was" : "were"} dropped.`);
  }
  if (res.skipped_not_accepted > 0) {
    parts.push(`${res.skipped_not_accepted} gap${res.skipped_not_accepted === 1 ? "" : "s"} skipped (no longer accepted).`);
  }
  if (res.skipped_not_found > 0) {
    parts.push(`${res.skipped_not_found} gap${res.skipped_not_found === 1 ? "" : "s"} skipped (not found).`);
  }
  return parts.join(" ");
}

export default function WorkspaceDirectionsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [stateFilter, setStateFilter] = useState<DirectionUserState | undefined>(undefined);
  const { data: acceptedGaps } = useSWR(["gaps", workspaceId, "accepted"], () => workspaces.listGaps(workspaceId, "accepted"));
  const { data, error, isLoading, mutate } = useSWR(
    ["directions", workspaceId, stateFilter],
    () => workspaces.listDirections(workspaceId, stateFilter ? { state: stateFilter } : undefined)
  );

  const [selectedGaps, setSelectedGaps] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  function toggleGap(id: string) {
    setSelectedGaps((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function generate() {
    setBusy(true);
    setGenError(null);
    setSummary(null);
    try {
      const res = await workspaces.generateDirections(workspaceId, Array.from(selectedGaps));
      setSummary(summarizeGeneration(res));
      setSelectedGaps(new Set());
      mutate();
    } catch (err) {
      if (err instanceof ApiError && err.code === "llm_key_required") {
        setGenError("No working LLM provider key is saved yet. Add one in Settings, then generate directions again.");
      } else {
        setGenError(err instanceof ApiError ? err.message : "Could not generate directions.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardBody className="space-y-3">
          <p className="text-sm font-medium text-ink">Generate directions from accepted gaps</p>
          {!acceptedGaps && <Skeleton className="h-8 w-48" />}
          {acceptedGaps && acceptedGaps.gaps.length === 0 && (
            <p className="text-sm text-ink-subtle">No accepted gaps yet. Accept a gap on the Gaps tab first.</p>
          )}
          {acceptedGaps && acceptedGaps.gaps.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {acceptedGaps.gaps.map((g) => (
                <label
                  key={g.gap_id}
                  className="flex max-w-xs items-center gap-1.5 rounded-sm border border-border-strong px-2.5 py-1.5 text-xs text-ink has-checked:border-accent has-checked:bg-accent-wash"
                >
                  <input type="checkbox" checked={selectedGaps.has(g.gap_id)} onChange={() => toggleGap(g.gap_id)} className="accent-[var(--color-accent)]" />
                  <span className="truncate">{g.statement}</span>
                </label>
              ))}
            </div>
          )}
          <Button size="sm" onClick={generate} loading={busy} disabled={selectedGaps.size === 0}>
            <Sparkle className="size-4" aria-hidden />
            Generate from {selectedGaps.size} gap{selectedGaps.size === 1 ? "" : "s"}
          </Button>
          {summary && <p className="text-xs text-ink-subtle">{summary}</p>}
          {genError && <InlineError message={genError} />}
        </CardBody>
      </Card>

      <div className="flex flex-wrap gap-4 border-b border-border pb-3 text-sm">
        {STATE_FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            onClick={() => setStateFilter(f.value)}
            aria-pressed={stateFilter === f.value}
            className={`border-b-2 pb-1 font-medium transition-colors ${
              stateFilter === f.value ? "border-accent text-ink" : "border-transparent text-ink-muted hover:text-ink"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {isLoading && <Skeleton className="h-40 w-full" />}
      {error && <ErrorState description={error instanceof ApiError ? error.message : undefined} onRetry={() => mutate()} />}
      {data && data.directions.length === 0 && (
        <EmptyState
          title={stateFilter ? `No ${stateFilter} directions` : "No directions yet"}
          description={stateFilter ? "Try another filter above." : "Generate directions from one or more accepted gaps above."}
        />
      )}
      {data && data.directions.length > 0 && (
        <ul className="space-y-3">
          {data.directions.map((d) => (
            <DirectionCard key={d.direction_id} direction={d} workspaceId={workspaceId} onChanged={() => mutate()} />
          ))}
        </ul>
      )}
    </div>
  );
}

function DirectionCard({
  direction,
  workspaceId,
  onChanged,
}: {
  direction: ResearchDirection;
  workspaceId: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [justFiled, setJustFiled] = useState(false);
  const withdrawn = direction.user_state === "rejected";

  async function setState(state: DirectionUserState) {
    setBusy(true);
    try {
      await workspaces.setDirectionState(workspaceId, direction.direction_id, state);
      if (state === "accepted") setJustFiled(true);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <li>
      <Card>
        <CardBody className="space-y-2">
          <div className={`flex flex-wrap items-start justify-between gap-2 ${withdrawn ? "stamp-withdrawn text-ink-subtle" : ""} ${justFiled ? "tracing-filed" : ""}`}>
            <p className="text-sm font-medium text-ink">{direction.proposal}</p>
            <ConfidenceBadge confidence={direction.confidence} />
          </div>
          <p className="text-xs text-ink-subtle">
            {direction.kind.replace(/_/g, " ")} · {direction.suggested_method}
            {direction.possible_dataset && ` · ${direction.possible_dataset}`}
          </p>
          <p className="text-sm text-ink-muted">{direction.motivation}</p>
          <p className="text-sm text-ink-muted">
            <span className="font-medium text-ink">Evaluation: </span>
            {direction.evaluation_strategy}
          </p>
          {direction.risks.length > 0 && (
            <p className="text-sm text-warning">
              <span className="font-medium">Risks: </span>
              {direction.risks.join("; ")}
            </p>
          )}
          {Object.keys(direction.critique).length > 0 && (
            <div className="space-y-0.5 font-mono text-[0.6875rem] text-ink-subtle">
              {Object.entries(direction.critique).map(([k, v]) => (
                <LeaderRow key={k} label={k} value={String(v)} />
              ))}
            </div>
          )}
          <ConfidenceBasisDisclosure basis={direction.confidence_basis} />
        </CardBody>
        <CardTracings
          entries={[
            { label: `from gap ${direction.gap_id}` },
            ...direction.related_papers.map((id) => ({ label: id, href: `/papers/${id}` })),
          ]}
        />
        <div className="rule-t flex items-center justify-between px-4 py-2">
          <span className="font-mono text-[0.6875rem] uppercase tracking-wider text-ink-subtle">
            {withdrawn ? "withdrawn" : direction.user_state}
          </span>
          <div className="flex items-center gap-4">
            <Button size="sm" variant="ghost" disabled={busy || withdrawn} onClick={() => setState("rejected")}>
              <X className="size-3.5" aria-hidden />
              Reject
            </Button>
            <Button size="sm" variant="secondary" disabled={busy || direction.user_state === "accepted"} onClick={() => setState("accepted")}>
              <Check className="size-3.5" aria-hidden />
              Accept
            </Button>
          </div>
        </div>
      </Card>
    </li>
  );
}
