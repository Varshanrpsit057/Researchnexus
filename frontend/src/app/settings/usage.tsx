"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ArrowSquareOut } from "@phosphor-icons/react/dist/ssr";
import { usage as usageApi } from "@/lib/api/endpoints";
import type { UsageRange, UsageReport, UsageTotals } from "@/lib/api/types";
import { providerName } from "@/lib/settings";
import { RANGES, billingConsoles, featureHint, featureLabel, formatTokens, plural, rangeLabel, shareOf, usageCaveats } from "@/lib/usage";
import { C, focusRing, panel, quietButton } from "../workspace/[id]/ui";
import { LoadFailure } from "./parts";

type Grouping = "feature" | "model" | "workspace";

const GROUPINGS: { value: Grouping; label: string; column: string }[] = [
  { value: "feature", label: "By feature", column: "Feature" },
  { value: "model", label: "By model", column: "Model" },
  { value: "workspace", label: "By workspace", column: "Workspace" },
];

interface Row extends UsageTotals {
  key: string;
  name: ReactNode;
  hint?: string;
}

function rowsOf(report: UsageReport, grouping: Grouping): Row[] {
  if (grouping === "feature") {
    return report.by_feature.map((r) => ({ ...r, key: r.feature, name: featureLabel(r.feature), hint: featureHint(r.feature) }));
  }
  if (grouping === "model") {
    return report.by_model.map((r) => ({
      ...r,
      key: `${r.provider}/${r.model}`,
      name: (
        <>
          {providerName(r.provider)} <span className="font-mono text-[12.5px]" style={{ color: C.muted }}>{r.model}</span>
        </>
      ),
    }));
  }
  return (report.by_workspace ?? []).map((r) => ({
    ...r,
    key: r.workspace_id ?? "none",
    name:
      r.workspace_id === null ? (
        "Outside a workspace"
      ) : r.title === null ? (
        <span style={{ color: C.muted }}>A deleted workspace</span>
      ) : (
        <Link href={`/workspace/${r.workspace_id}`} className={`rounded-sm underline decoration-[rgba(93,240,168,0.4)] underline-offset-4 hover:text-white ${focusRing}`}>
          {r.title}
        </Link>
      ),
    hint: r.workspace_id === null ? "Paper profiles and discovery search plans." : undefined,
  }));
}

function Segmented<T extends string>({ label, options, value, onChange }: { label: string; options: { value: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(o.value)}
            className={`min-h-9 rounded-full px-3.5 text-[13px] font-medium transition-colors ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
            style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** A figure with what it includes beneath it ("4,100 cached"). */
function Figure({ value, part, partLabel, tone }: { value: number; part?: number; partLabel?: string; tone?: string }) {
  return (
    <>
      <span className="block tabular-nums">{formatTokens(value)}</span>
      {part ? (
        <span className="block text-[12px] tabular-nums" style={{ color: tone ?? C.muted }}>
          {formatTokens(part)} {partLabel}
        </span>
      ) : null}
    </>
  );
}

function UsageTable({ rows, totals, column }: { rows: Row[]; totals: UsageTotals; column: string }) {
  const num = "whitespace-nowrap px-3 py-3 text-right align-top";
  return (
    <table className="w-full border-collapse text-[14px]">
      <caption className="sr-only">Model usage {column.toLowerCase() === "feature" ? "by feature" : `by ${column.toLowerCase()}`}</caption>
      <thead>
        <tr className="whitespace-nowrap text-[12.5px] font-semibold" style={{ color: C.muted }}>
          <th scope="col" className="py-2 pl-4 pr-3 text-left font-semibold">
            {column}
          </th>
          <th scope="col" className="px-3 py-2 text-right font-semibold">
            Calls
          </th>
          <th scope="col" className="px-3 py-2 text-right font-semibold">
            Input tokens
          </th>
          <th scope="col" className="px-3 py-2 text-right font-semibold">
            Output tokens
          </th>
          <th scope="col" className="w-[22%] py-2 pl-3 pr-4 text-right font-semibold">
            Total
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className="border-t" style={{ borderColor: C.line }}>
            <th scope="row" className="py-3 pl-4 pr-3 text-left align-top font-medium [overflow-wrap:anywhere]">
              {r.name}
              {r.hint && (
                <span className="mt-0.5 block text-[12px] font-normal" style={{ color: C.muted }}>
                  {r.hint}
                </span>
              )}
            </th>
            <td className={num}>
              <span className="block tabular-nums">{formatTokens(r.calls)}</span>
              {r.failed_calls > 0 && (
                <span className="block text-[12px] tabular-nums" style={{ color: C.warning }}>
                  {formatTokens(r.failed_calls)} failed
                </span>
              )}
            </td>
            <td className={num}>
              <Figure value={r.prompt_tokens} part={r.cached_prompt_tokens} partLabel="cached" />
            </td>
            <td className={num}>
              <Figure value={r.completion_tokens} part={r.reasoning_tokens} partLabel="reasoning" />
            </td>
            <td className="whitespace-nowrap py-3 pl-3 pr-4 text-right align-top">
              <span className="block font-semibold tabular-nums">{formatTokens(r.total_tokens)}</span>
              <span className="mt-1.5 block h-[3px] overflow-hidden rounded-full" style={{ background: "rgba(150,175,230,.14)" }} aria-hidden>
                <span className="ml-auto block h-full rounded-full" style={{ width: `${shareOf(r.total_tokens, totals.total_tokens) * 100}%`, background: C.mint, opacity: 0.8 }} />
              </span>
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="border-t-2" style={{ borderColor: C.lineStrong }}>
          <th scope="row" className="py-3 pl-4 pr-3 text-left font-semibold">
            All
          </th>
          <td className={`${num} font-semibold tabular-nums`}>{formatTokens(totals.calls)}</td>
          <td className={`${num} font-semibold`}>
            <Figure value={totals.prompt_tokens} part={totals.cached_prompt_tokens} partLabel="cached" />
          </td>
          <td className={`${num} font-semibold`}>
            <Figure value={totals.completion_tokens} part={totals.reasoning_tokens} partLabel="reasoning" />
          </td>
          <td className="py-3 pl-3 pr-4 text-right font-semibold tabular-nums">{formatTokens(totals.total_tokens)}</td>
        </tr>
      </tfoot>
    </table>
  );
}

/**
 * What the user's model keys have used, from the usage ledger (remediation
 * Phase 5): the provider's own token counts over a stated range, grouped by
 * what the calls were for, which model answered, or which workspace. No cost.
 */
export function UsagePanel({ ready }: { ready: boolean }) {
  const [range, setRange] = useState<UsageRange>("30d");
  const [grouping, setGrouping] = useState<Grouping>("feature");
  const q = useSWR(ready ? ["usage", range] : null, () => usageApi.get(range), { keepPreviousData: true });
  const report = q.data;

  if (q.error && !report) return <LoadFailure what="your model usage" onRetry={() => q.mutate()} />;

  const span = report ? rangeLabel(report) : null;
  const switching = report !== undefined && report.range.key !== range;
  const column = GROUPINGS.find((g) => g.value === grouping)!.column;
  const consoles = report ? billingConsoles(report) : [];

  return (
    <div className="rounded-2xl" style={panel} data-testid="usage">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3" style={{ borderColor: C.line }}>
        <Segmented label="Range" options={RANGES.map((r) => ({ value: r.key, label: r.label }))} value={range} onChange={setRange} />
        <Segmented label="Group" options={GROUPINGS} value={grouping} onChange={setGrouping} />
      </div>

      {!report ? (
        <div role="status" className="h-56 motion-safe:animate-pulse">
          <span className="sr-only">Loading your model usage…</span>
        </div>
      ) : (
        <div aria-busy={switching} className="transition-opacity duration-150" style={{ opacity: switching ? 0.55 : 1 }}>
          <p className="px-4 pt-4 text-[15px] leading-relaxed" data-testid="usage-summary">
            {report.totals.calls === 0 ? (
              <span style={{ color: C.muted }}>
                {report.range.days === null
                  ? "No model calls yet."
                  : `No model calls in the last ${RANGES.find((r) => r.key === report.range.key)?.label ?? `${report.range.days} days`}.`}
              </span>
            ) : (
              <>
                <span className="font-semibold tabular-nums">{plural(report.totals.total_tokens, "token")}</span>{" "}
                <span style={{ color: C.muted }}>
                  across {plural(report.totals.calls, "call")} ·{" "}
                  <span title={span?.exact ?? undefined} className="underline decoration-dotted underline-offset-4">
                    {span?.text}
                  </span>
                </span>
              </>
            )}
          </p>

          {report.totals.calls > 0 && (
            <div className="mt-3 overflow-x-auto">
              <UsageTable rows={rowsOf(report, grouping)} totals={report.totals} column={column} />
            </div>
          )}

          <div className="space-y-2 border-t px-4 py-4 text-[13px] leading-relaxed" style={{ borderColor: C.line, color: C.muted }}>
            {usageCaveats(report.totals).map((c) => (
              <p key={c}>{c}</p>
            ))}
            <p data-testid="usage-cost-note">
              No cost is shown. Providers don&apos;t send a price with each call, and what you pay depends on your plan, free quota and discounts, which
              ResearchNexus can&apos;t see.
              {consoles.length > 0 && (
                <>
                  {" "}
                  Your exact bill is in {consoles.length === 1 ? "your provider's console" : "each provider's console"}:{" "}
                  {consoles.map((c, i) => (
                    <span key={c.url}>
                      {i > 0 && ", "}
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noreferrer"
                        className={`inline-flex items-center gap-1 rounded-sm underline decoration-[rgba(93,240,168,0.4)] underline-offset-4 hover:text-white ${focusRing}`}
                        style={{ color: C.ink }}
                      >
                        {c.name}
                        <ArrowSquareOut className="size-3.5" aria-hidden />
                        <span className="sr-only">(opens in a new tab)</span>
                      </a>
                    </span>
                  ))}
                  .
                </>
              )}
            </p>
            <p>Checking a key from this page uses a few tokens that aren&apos;t counted here.</p>
          </div>
        </div>
      )}
    </div>
  );
}
