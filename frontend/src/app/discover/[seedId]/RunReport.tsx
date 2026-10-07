"use client";

import { WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { CINEMATIC } from "@/lib/cinematic-theme";
import {
  SOURCE_LABEL,
  SOURCE_ORDER,
  STEP_LABEL,
  STEP_ORDER,
  STRATEGY_LABEL,
  formatSeconds,
  runIssues,
  sourceSummary,
  strategyNote,
} from "@/lib/discovery";
import type { DiscoveryStrategy, RelatedRunSummary } from "@/lib/api/types";

const C = CINEMATIC;
const STRATEGIES: DiscoveryStrategy[] = ["keyword", "query_expansion", "citation", "recommendation", "semantic", "semantic_doc"];

/** What a finished run is missing, said plainly -- and, on request, how it
 * ran step by step. Runs saved before the report existed show their counts. */
export function RunReport({ run }: { run: RelatedRunSummary }) {
  const report = run.report ?? null;
  const issues = report ? runIssues(report, run.counts) : { incomplete: [], notes: [] };

  return (
    <div className="mt-2 flex flex-wrap items-start gap-x-5 gap-y-1.5 text-[13px]">
      {issues.incomplete.length > 0 && (
        <details data-testid="run-incomplete" className="max-w-3xl">
          <summary className="inline-flex cursor-pointer items-center gap-1.5 font-semibold" style={{ color: C.warning }}>
            <WarningCircle className="size-4 shrink-0" weight="bold" aria-hidden />
            Partial results: some of the search didn&apos;t finish ({issues.incomplete.length})
          </summary>
          <ul className="mt-1.5 list-inside list-disc space-y-0.5" style={{ color: C.muted }}>
            {issues.incomplete.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      )}
      {issues.notes.map((line) => (
        <p key={line} style={{ color: C.muted2 }}>
          {line}
        </p>
      ))}
      <details style={{ color: C.muted }}>
        <summary className="cursor-pointer" style={{ color: C.muted2 }}>
          How this search ran
        </summary>
        <div className="mt-2 space-y-3 rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(0,0,0,.3)" }}>
          {report && (
            <>
              <p>Searched in {formatSeconds(report.elapsed_s)}, then ranked.</p>
              <ul className="space-y-0.5 font-mono" aria-label="Steps">
                {STEP_ORDER.filter((s) => report.steps[s] && report.steps[s]!.state !== "pending").map((s) => {
                  const step = report.steps[s]!;
                  return (
                    <li key={s}>
                      {STEP_LABEL[s].toLowerCase()} · {step.state}
                      {step.seconds != null && ` · ${formatSeconds(step.seconds)}`}
                      {step.note && ` · ${step.note}`}
                    </li>
                  );
                })}
              </ul>
              <ul className="space-y-0.5" aria-label="Strategies">
                {STRATEGIES.filter((s) => report.strategies[s]).map((s) => {
                  const entry = report.strategies[s]!;
                  const note = strategyNote(s, entry);
                  return (
                    <li key={s}>
                      {STRATEGY_LABEL[s]}: {entry.found} {entry.state === "timed_out" ? "(stopped at its limit)" : entry.state === "failed" ? "(failed)" : ""}
                      {entry.seconds != null && ` in ${formatSeconds(entry.seconds)}`}
                      {note && ` — ${note}`}
                    </li>
                  );
                })}
              </ul>
              <ul className="space-y-0.5" aria-label="Sources">
                {SOURCE_ORDER.filter((s) => report.sources[s]).map((s) => (
                  <li key={s}>
                    {SOURCE_LABEL[s]}: {sourceSummary(report.sources[s])}
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="space-y-1 font-mono">
            <p>found {run.counts.raw}</p>
            <p>after dedupe {run.counts.after_dedupe}</p>
            <p>after filter {run.counts.after_filter}</p>
            <p>set aside as off-topic {run.counts.off_topic ?? 0}</p>
            <p>extra citation hop {run.extra_citation_hop_used ? "used" : "not used"}</p>
          </div>
        </div>
      </details>
    </div>
  );
}
