import { Info } from "@phosphor-icons/react/dist/ssr";

/** A label pinned to its value across a dotted rule, the way a table of
 * contents pins a heading to its page number -- a leader line, standing in
 * here for the tensegrity-column raise's leader-line fact-pinning in dense,
 * evidential views instead of a wrapped badge-like cluster. */
export function LeaderRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="shrink-0">{label}</span>
      <span aria-hidden className="min-w-4 flex-1 translate-y-[-3px] border-b border-dotted border-border-strong" />
      <span className="shrink-0 text-ink-muted">{value}</span>
    </div>
  );
}

/** A generic disclosure for the `confidence_basis` record that TrailEdge,
 * ResearchGap, and ResearchDirection all carry -- the system's own reasoning
 * for the confidence band it assigned, fetched everywhere but previously
 * rendered nowhere (contradicts the product principle that this kind of
 * reasoning is first-class UI, not buried). One shared component since the
 * shape and intent are identical in all three call sites. */
export function ConfidenceBasisDisclosure({ basis }: { basis: Record<string, unknown> }) {
  const entries = Object.entries(basis);
  if (entries.length === 0) return null;

  return (
    <details>
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-ink-subtle hover:text-ink-muted">
        <Info className="size-3" aria-hidden />
        Why this confidence
      </summary>
      <div className="rule-t mt-1 space-y-0.5 bg-surface-sunken px-2.5 py-1.5 font-mono text-[0.6875rem] text-ink-subtle">
        {entries.map(([key, value]) => (
          <LeaderRow key={key} label={key.replace(/_/g, " ")} value={typeof value === "object" ? JSON.stringify(value) : String(value)} />
        ))}
      </div>
    </details>
  );
}
