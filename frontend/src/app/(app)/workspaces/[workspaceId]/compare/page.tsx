"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { useWorkspace } from "../layout";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { Card, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { EmptyState, InlineError, Skeleton } from "@/components/ui/States";

export default function WorkspaceComparePage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { data: workspace } = useWorkspace(workspaceId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A comparison is real synthesis work, computed and persisted server
  // side -- without this, leaving Compare and coming back re-showed "no
  // comparison yet" even for a workspace with a real one on record,
  // indistinguishable from never having run one, and re-running meant
  // re-billing the LLM to see what was already there.
  const {
    data: result,
    isLoading: resultLoading,
    mutate: mutateResult,
  } = useSWR(["compare", workspaceId], async () => {
    try {
      return await workspaces.getLatestComparison(workspaceId);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });

  if (!workspace) return null;

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runCompare() {
    setBusy(true);
    setError(null);
    try {
      const res = await workspaces.compare(workspaceId, { paper_ids: Array.from(selected) });
      await mutateResult(res, { revalidate: false });
    } catch (err) {
      if (err instanceof ApiError && err.code === "llm_key_required") {
        setError("No working LLM provider key is saved yet. Add one in Settings, then compare again.");
      } else {
        setError(err instanceof ApiError ? err.message : "Comparison failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardBody className="space-y-3">
          <p className="text-sm font-medium text-ink">Select papers to compare</p>
          <div className="flex flex-wrap gap-2">
            {workspace.papers.map((p) => (
              <label
                key={p.paper_id}
                className="flex items-center gap-1.5 rounded-sm border border-border-strong px-2.5 py-1.5 text-sm text-ink has-checked:border-accent has-checked:bg-accent-wash"
              >
                <input type="checkbox" checked={selected.has(p.paper_id)} onChange={() => toggle(p.paper_id)} className="accent-[var(--color-accent)]" />
                <span className="font-mono text-xs">{p.paper_id}</span>
              </label>
            ))}
          </div>
          <Button size="sm" onClick={runCompare} loading={busy} disabled={selected.size < 2}>
            Compare {selected.size} papers
          </Button>
          {selected.size < 2 && <p className="text-xs text-ink-subtle">Select at least 2 papers.</p>}
          {error && <InlineError message={error} />}
        </CardBody>
      </Card>

      {resultLoading && <Skeleton className="h-40 w-full" />}

      {!resultLoading && result && result.rows.length > 0 && (
        <Card>
          <CardBody className="space-y-3">
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[0.6875rem] text-ink-subtle">
              <span>{Math.round(result.coverage * 100)}% coverage</span>
              {result.decontext_eval != null && <span>{Math.round(result.decontext_eval * 100)}% decontextualised</span>}
              {result.warnings && result.warnings.length > 0 && <span className="text-warning">{result.warnings.join(", ")}</span>}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border-strong text-left">
                    <th className="py-2 pr-3 font-medium text-ink-muted">Paper</th>
                    {result.schema.map((col) => (
                      <th key={col} className="py-2 pr-3 font-medium text-ink-muted">
                        {col.replace(/_/g, " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row) => (
                    <tr key={row.paper_id} className="border-b border-border align-top">
                      <td className="py-2 pr-3 font-mono text-xs text-ink-subtle">{row.paper_id}</td>
                      {result.schema.map((col) => {
                        const cell = row.cells[col];
                        return (
                          <td key={col} className="max-w-64 py-2 pr-3 text-ink">
                            {cell?.text ?? <span className="text-ink-subtle">—</span>}
                            {cell?.conflicting && cell.conflicting.length > 0 && (
                              <span className="mt-0.5 block text-xs text-warning">conflicts with {cell.conflicting.length}</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}

      {!resultLoading && !result && (
        <EmptyState title="No comparison yet" description="Pick two or more papers above and run a comparison." />
      )}
    </div>
  );
}
