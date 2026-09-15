"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { Copy } from "@phosphor-icons/react/dist/ssr";
import { useWorkspace } from "../layout";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { CitationFormat, CitationsResponse } from "@/lib/api/types";
import { Card, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { EmptyState, InlineError } from "@/components/ui/States";

const FORMATS: CitationFormat[] = ["apa", "ieee", "bibtex"];

export default function WorkspaceCitationsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { data: workspace } = useWorkspace(workspaceId);
  const [formats, setFormats] = useState<Set<CitationFormat>>(new Set(FORMATS));
  const [result, setResult] = useState<CitationsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!workspace) return null;

  function toggleFormat(f: CitationFormat) {
    setFormats((prev) => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  }

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const res = await workspaces.citations(workspaceId, { formats: Array.from(formats) });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate citations.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardBody className="space-y-3">
          <p className="text-sm font-medium text-ink">Formats</p>
          <div className="flex flex-wrap gap-2">
            {FORMATS.map((f) => (
              <label
                key={f}
                className="flex items-center gap-1.5 rounded-sm border border-border-strong px-2.5 py-1.5 text-sm uppercase text-ink has-checked:border-accent has-checked:bg-accent-wash"
              >
                <input type="checkbox" checked={formats.has(f)} onChange={() => toggleFormat(f)} className="accent-[var(--color-accent)]" />
                {f}
              </label>
            ))}
          </div>
          <Button size="sm" onClick={generate} loading={busy} disabled={formats.size === 0}>
            Generate citations for all {workspace.papers.length} papers
          </Button>
          {error && <InlineError message={error} />}
        </CardBody>
      </Card>

      {result && result.unresolved.length > 0 && (
        <p className="text-xs text-warning">{result.unresolved.length} paper(s) could not be resolved</p>
      )}

      {result && result.citations.length === 0 && <EmptyState title="No citations generated yet" />}

      {result && result.citations.length > 0 && (
        <ul className="space-y-3">
          {result.citations.map((c) => (
            <li key={c.paper_id}>
              <Card>
                <CardBody className="space-y-2">
                  <p className="font-mono text-xs text-ink-subtle">{c.paper_id}</p>
                  {FORMATS.filter((f) => formats.has(f)).map((f) => (
                    <div key={f} className="rule-t flex items-start justify-between gap-2 bg-surface-sunken px-3 py-2">
                      <div>
                        <p className="text-[0.6875rem] font-medium uppercase tracking-wider text-ink-subtle">{f}</p>
                        {c.formatted[f] ? (
                          <p className={`text-sm text-ink ${f === "bibtex" ? "font-mono whitespace-pre-wrap" : ""}`}>{c.formatted[f]}</p>
                        ) : (
                          <p className="text-sm text-ink-subtle">Not available</p>
                        )}
                      </div>
                      {c.formatted[f] && (
                        <button
                          type="button"
                          onClick={() => navigator.clipboard?.writeText(c.formatted[f] ?? "")}
                          aria-label={`Copy ${f} citation`}
                          className="shrink-0 rounded-sm p-1.5 text-ink-muted hover:bg-surface-raised hover:text-ink"
                        >
                          <Copy className="size-4" aria-hidden />
                        </button>
                      )}
                    </div>
                  ))}
                </CardBody>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
