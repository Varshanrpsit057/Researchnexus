"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { ArrowSquareOut, Check, MagnifyingGlass, SlidersHorizontal, WarningCircle, X } from "@phosphor-icons/react/dist/ssr";
import { papers } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { CINEMATIC } from "@/lib/cinematic-theme";
import {
  CRITERIA,
  CRITERION_COLOR,
  DEFAULT_CRITERIA,
  criteriaName,
  SIGNALS,
  bandReason,
  criteriaError,
  criteriaShares,
  explainRank,
  sameCriteria,
  writeCriteria,
} from "@/lib/ranking";
import {
  FOUND_BY_OPTIONS,
  SORT_OPTIONS,
  authorLine,
  filterResults,
  foundBy,
  sortResults,
  type FoundByFilter,
  publisherOptions,
  type PublisherFilter,
  type ResultSort,
} from "@/lib/discovery-results";
import { RankingCriteriaControls } from "@/components/discovery/RankingCriteriaControls";
import { DEFAULT_PUBLISHERS, publishersPhrase, samePublishers, useSavedPublishers } from "@/lib/publishers";
import type { Confidence, RankingCriteria, RelatedResponse, RelatedResult } from "@/lib/api/types";

const C = CINEMATIC;
const BANDS: { value: Confidence | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];
const BAND_COLOR: Record<Confidence, string> = { high: C.mint, medium: "#9fb3e6", low: C.muted2 };
const DEFAULT_BANDS = { high: 0.66, medium: 0.33 };
const fieldStyle = { background: "rgba(255,255,255,.04)", border: `1px solid ${C.line}`, color: C.ink } as const;

/** A paper's score as a bar of its signals' contributions: the bar is as long
 * as the score, each segment as long as what that signal added. */
function ContributionStrip({ result }: { result: RelatedResult }) {
  const rows = result.explanation?.contributions ?? [];
  const score = result.fused_score ?? 0;
  if (rows.length === 0) {
    return <div className="h-1.5 rounded-full" style={{ width: `${Math.round(score * 100)}%`, background: C.lineStrong }} aria-hidden />;
  }
  return (
    <div className="flex h-1.5 w-full gap-[2px]" aria-hidden>
      {rows
        .filter((c) => c.contribution > 0)
        .map((c) => (
          <span
            key={c.signal}
            title={`${SIGNALS[c.signal]?.label ?? c.signal}: adds ${c.contribution.toFixed(2)} of ${score.toFixed(2)}`}
            className="h-full rounded-[2px]"
            style={{ width: `${c.contribution * 100}%`, background: CRITERION_COLOR[SIGNALS[c.signal]?.criterion ?? "topic"] }}
          />
        ))}
    </div>
  );
}

function BandLabel({ band }: { band: Confidence | null }) {
  if (!band) return <span style={{ color: C.muted2 }}>not ranked</span>;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="size-1.5 rounded-full" style={{ background: BAND_COLOR[band] }} aria-hidden />
      {band}
    </span>
  );
}

function ResultRow({
  result,
  index,
  focused,
  selected,
  onFocus,
  onToggle,
}: {
  result: RelatedResult;
  index: number;
  focused: boolean;
  selected: boolean;
  onFocus: () => void;
  onToggle: () => void;
}) {
  const p = result.paper;
  return (
    <li
      className="grid grid-cols-[1.25rem_2.25rem_minmax(0,1fr)_7.5rem] items-start gap-x-3 px-3 py-3 transition-colors"
      style={{ background: focused ? "rgba(93,240,168,.08)" : undefined }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={selected}
        aria-label={`Select ${p.title}`}
        className="mt-0.5 flex size-5 items-center justify-center rounded-md transition-colors"
        style={selected ? { background: C.mint, color: C.mintInk } : { background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}` }}
      >
        {selected && <Check className="size-3.5" weight="bold" aria-hidden />}
      </button>
      <span className="pt-0.5 font-mono text-xs tabular-nums" style={{ color: C.muted2 }}>
        {result.final_rank != null ? `#${result.final_rank}` : "–"}
      </span>
      <button type="button" data-row={index} onClick={onFocus} onFocus={onFocus} className="min-w-0 text-left" aria-current={focused || undefined}>
        <span className="block text-[14px] font-semibold leading-snug [text-wrap:pretty]" style={{ color: C.ink }}>
          {p.title}
        </span>
        <span className="mt-0.5 block truncate text-xs" style={{ color: C.muted2 }}>
          {authorLine(p.authors)}
          {p.year != null && ` · ${p.year}`}
          {p.venue && ` · ${p.venue}`}
          {p.publisher && p.publisher !== p.venue && ` · ${p.publisher}`}
        </span>
      </button>
      <div className="pt-0.5 text-right">
        <div className="flex items-center justify-end gap-2 font-mono text-xs tabular-nums" style={{ color: C.muted }}>
          <BandLabel band={result.band} />
          {result.fused_score != null && <span>{result.fused_score.toFixed(2)}</span>}
        </div>
        <div className="mt-1.5">
          <ContributionStrip result={result} />
        </div>
      </div>
    </li>
  );
}

function RankDetail({
  result,
  run,
  selected,
  onToggle,
}: {
  result: RelatedResult;
  run: RelatedResponse["run"];
  selected: boolean;
  onToggle: () => void;
}) {
  const p = result.paper;
  const score = result.fused_score ?? 0;
  const why = result.explanation ? explainRank(result.explanation, score) : { rows: [], missing: [] };
  const criteria = run.ranking_criteria;
  const shares = criteria ? criteriaShares(criteria) : null;
  const link = p.doi ? `https://doi.org/${p.doi}` : p.url;
  return (
    <div className="space-y-5" data-testid="result-detail">
      <div>
        <h2 className="text-lg font-bold leading-snug [text-wrap:balance]">{p.title}</h2>
        <p className="mt-1.5 text-sm" style={{ color: C.muted }}>
          {p.authors.length > 0 ? p.authors.join(", ") : "Authors unknown"}
        </p>
        <p className="mt-0.5 text-sm" style={{ color: C.muted2 }}>
          {[p.year, p.venue, p.publisher !== p.venue ? p.publisher : null].filter(Boolean).join(" · ") || "Year and venue unknown"}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onToggle}
            className="rounded-full px-4 py-1.5 text-sm font-semibold"
            style={selected ? { color: C.mintInk, background: C.mint } : { color: C.ink, border: `1px solid ${C.lineStrong}` }}
          >
            {selected ? "Selected for a workspace" : "Select for a workspace"}
          </button>
          {link && (
            <a href={link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm hover:underline" style={{ color: C.mint }}>
              View source <ArrowSquareOut className="size-3.5" aria-hidden />
            </a>
          )}
        </div>
      </div>

      <section aria-labelledby="why-rank">
        <h3 id="why-rank" className="text-sm font-semibold">
          Why this rank
        </h3>
        {result.final_rank != null && result.band ? (
          <p className="mt-1 text-sm" style={{ color: C.muted }}>
            #{result.final_rank} of {run.counts.after_filter}, {result.band} band. {bandReason(score, result.band, run.bands ?? DEFAULT_BANDS)}
          </p>
        ) : (
          <p className="mt-1 text-sm" style={{ color: C.muted }}>
            Not ranked yet.
          </p>
        )}
        {why.rows.length > 0 ? (
          <>
            <table className="mt-3 w-full text-[13px]">
              <caption className="sr-only">What each signal added to this paper&apos;s score</caption>
              <thead>
                <tr className="text-left text-xs" style={{ color: C.muted2 }}>
                  <th scope="col" className="pb-1.5 font-medium">Signal</th>
                  <th scope="col" className="pb-1.5 text-right font-medium">Value</th>
                  <th scope="col" className="pb-1.5 text-right font-medium">Weight</th>
                  <th scope="col" className="pb-1.5 text-right font-medium">Adds</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {why.rows.map((row) => (
                  <tr key={row.signal} className="border-t" style={{ borderColor: C.line }}>
                    <th scope="row" className="py-1.5 pr-2 text-left font-sans font-normal" style={{ color: C.ink }}>
                      <span className="flex items-center gap-2">
                        <span className="size-2 shrink-0 rounded-sm" style={{ background: CRITERION_COLOR[row.criterion] }} aria-hidden />
                        {row.label}
                      </span>
                    </th>
                    <td className="py-1.5 text-right" style={{ color: C.muted }}>{row.value.toFixed(2)}</td>
                    <td className="py-1.5 text-right" style={{ color: C.muted }}>{Math.round(row.weight * 100)}%</td>
                    <td className="py-1.5 text-right" style={{ color: C.ink }}>
                      {row.contribution.toFixed(2)}
                      <span className="ml-1.5 text-[11px]" style={{ color: C.muted2 }}>{row.share}%</span>
                    </td>
                  </tr>
                ))}
                <tr className="border-t" style={{ borderColor: C.lineStrong }}>
                  <th scope="row" colSpan={3} className="py-1.5 text-left font-sans font-semibold">Score</th>
                  <td className="py-1.5 text-right font-semibold">{score.toFixed(2)}</td>
                </tr>
              </tbody>
            </table>
            <p className="mt-2 text-[12.5px]" style={{ color: C.muted2 }}>
              Each signal adds its value times its weight; the weights come from the ranking criteria
              {why.missing.length > 0 && `, shared among the signals that could be computed. Not computed for this paper: ${why.missing.join(", ")}`}.
            </p>
          </>
        ) : result.explanation && result.explanation.bullet_reasons.length > 0 ? (
          <>
            <p className="mt-2 text-[12.5px]" style={{ color: C.muted2 }}>
              This ranking was saved before scores were broken down by signal; its own reasons were:
            </p>
            <ul className="mt-1 list-inside list-disc space-y-0.5 text-sm" style={{ color: C.muted }}>
              {result.explanation.bullet_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </>
        ) : null}
        {shares && criteria && (
          <p className="mt-2 text-[12.5px]" style={{ color: C.muted2 }}>
            Ranked by {criteriaName(criteria)}:{" "}
            {CRITERIA.filter(({ key }) => shares[key] > 0)
              .map(({ key, label }) => `${label.toLowerCase()} ${shares[key]}%`)
              .join(", ")}
            .{shares.publisher > 0 && ` Preferred publishers: ${publishersPhrase(run.preferred_publishers ?? DEFAULT_PUBLISHERS)}.`}
          </p>
        )}
      </section>

      <section aria-labelledby="found-how">
        <h3 id="found-how" className="text-sm font-semibold">
          How it was found
        </h3>
        <p className="mt-1 text-sm" style={{ color: C.muted }}>
          {foundBy(result).join(" · ") || "Not recorded"}
        </p>
      </section>

      {p.abstract && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold">Abstract</summary>
          <p className="mt-2 max-w-[65ch] text-sm leading-relaxed" style={{ color: C.muted }}>
            {p.abstract}
          </p>
        </details>
      )}
    </div>
  );
}

/** A run's results for research use: a compact ranked list with filters and
 * sorting, one paper's full record and ranking decision beside it, and the
 * ranking criteria to re-weigh the run (remediation Phases 9-10). */
export function Results({
  seedId,
  runId,
  related,
  selected,
  onToggle,
  onReranked,
  onCreateWorkspace,
}: {
  seedId: string;
  runId: string;
  related: RelatedResponse;
  selected: Set<string>;
  onToggle: (paperId: string) => void;
  onReranked: (next: RelatedResponse) => void;
  onCreateWorkspace: () => void;
}) {
  const [query, setQuery] = useState("");
  const [band, setBand] = useState<Confidence | "all">("all");
  const [foundByFilter, setFoundBy] = useState<FoundByFilter>("all");
  const [publisherFilter, setPublisher] = useState<PublisherFilter>("all");
  const [sort, setSort] = useState<ResultSort>("rank");
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [showCriteria, setShowCriteria] = useState(false);
  const ranked = related.run.ranking_criteria ?? null;
  const [draft, setDraft] = useState<RankingCriteria>(ranked ?? DEFAULT_CRITERIA);
  const [reranking, setReranking] = useState(false);
  const [rerankError, setRerankError] = useState<string | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  // the publishers this run was ranked with (older runs: the reader's saved ones)
  const savedPublishers = useSavedPublishers();
  const runPreferred = related.run.preferred_publishers ?? savedPublishers;

  const visible = useMemo(
    () => sortResults(filterResults(related.results, { query, band, foundBy: foundByFilter, publisher: publisherFilter, preferred: runPreferred }), sort),
    [related.results, query, band, foundByFilter, publisherFilter, sort, runPreferred],
  );
  const focused = visible.find((r) => r.paper.id === focusedId) ?? visible[0] ?? null;
  const filtering = query.trim() !== "" || band !== "all" || foundByFilter !== "all" || publisherFilter !== "all";
  const publisherChoices = useMemo(() => publisherOptions(related.results, runPreferred), [related.results, runPreferred]);

  function onListKey(e: KeyboardEvent<HTMLUListElement>) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const current = Number((document.activeElement as HTMLElement | null)?.dataset.row ?? -1);
    const next = Math.min(Math.max(current + (e.key === "ArrowDown" ? 1 : -1), 0), visible.length - 1);
    const target = listRef.current?.querySelector<HTMLButtonElement>(`[data-row="${next}"]`);
    if (target) {
      e.preventDefault();
      target.focus();
      target.scrollIntoView({ block: "nearest" });
    }
  }

  async function rerank() {
    if (criteriaError(draft)) return;
    setReranking(true);
    setRerankError(null);
    try {
      const next = await papers.rerankRelated(seedId, runId, draft, [...savedPublishers]);
      writeCriteria(draft); // the next discovery ranks the same way
      onReranked(next);
      setShowCriteria(false);
    } catch (err) {
      setRerankError(err instanceof ApiError ? err.message : "Could not re-rank these results.");
    } finally {
      setReranking(false);
    }
  }

  return (
    <div className="mt-5">
      <div className="flex flex-wrap items-center gap-2.5" role="toolbar" aria-label="Filter and sort the results">
        <label className="relative flex min-w-[16rem] flex-1 items-center">
          <span className="sr-only">Search the results</span>
          <MagnifyingGlass className="pointer-events-none absolute left-3 size-4" style={{ color: C.muted2 }} aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles, authors, venues"
            className="h-9 w-full rounded-full pl-9 pr-3 text-sm outline-none focus-visible:ring-2"
            style={fieldStyle}
          />
        </label>
        <div className="flex gap-1" role="group" aria-label="Confidence band">
          {BANDS.map((b) => (
            <button
              key={b.value}
              type="button"
              onClick={() => setBand(b.value)}
              aria-pressed={band === b.value}
              className="h-9 rounded-full px-3.5 text-xs font-medium transition-colors"
              style={band === b.value ? { color: C.mintInk, background: C.mint } : { ...fieldStyle, color: C.muted }}
            >
              {b.label}
            </button>
          ))}
        </div>
        <label className="text-xs" style={{ color: C.muted }}>
          <span className="sr-only">Found by</span>
          <select value={foundByFilter} onChange={(e) => setFoundBy(e.target.value as FoundByFilter)} className="h-9 rounded-full px-3 text-xs" style={fieldStyle}>
            {FOUND_BY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs" style={{ color: C.muted }}>
          <span className="sr-only">Publisher</span>
          <select value={publisherFilter} onChange={(e) => setPublisher(e.target.value)} className="h-9 max-w-[15rem] rounded-full px-3 text-xs" style={fieldStyle}>
            {publisherChoices.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="inline-flex items-center gap-2 text-xs" style={{ color: C.muted }}>
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as ResultSort)} className="h-9 rounded-full px-3 text-xs" style={fieldStyle}>
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => setShowCriteria((v) => !v)}
          aria-expanded={showCriteria}
          aria-controls="rerank-panel"
          className="inline-flex h-9 items-center gap-2 rounded-full px-3.5 text-xs font-semibold transition-colors hover:bg-white/10"
          style={{ border: `1px solid ${C.lineStrong}`, color: C.ink }}
        >
          <SlidersHorizontal className="size-4" aria-hidden />
          Ranking criteria{ranked && !sameCriteria(ranked, DEFAULT_CRITERIA) ? ": yours" : ""}
        </button>
        <span className="ml-auto flex items-center gap-3">
          <span className="text-xs tabular-nums" style={{ color: C.muted }}>
            {selected.size} selected
          </span>
          <button
            type="button"
            onClick={onCreateWorkspace}
            className="h-9 rounded-full px-4 text-sm font-semibold"
            style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
          >
            Create workspace{selected.size > 0 ? ` with ${selected.size} paper${selected.size === 1 ? "" : "s"}` : ""}
          </button>
        </span>
      </div>

      {showCriteria && (
        <div id="rerank-panel" className="mt-3 rounded-2xl px-5 py-4" style={{ background: C.glass, border: `1px solid ${C.lineStrong}` }}>
          <div className="flex items-start justify-between gap-4">
            <p className="max-w-[60ch] text-sm" style={{ color: C.muted }}>
              Re-weigh this run. Nothing is searched again: each paper&apos;s signals are already measured, and only how much each counts changes.
            </p>
            <button type="button" onClick={() => setShowCriteria(false)} aria-label="Close ranking criteria" className="rounded-full p-1.5 hover:bg-white/10">
              <X className="size-4" aria-hidden />
            </button>
          </div>
          <div className="mt-4">
            <RankingCriteriaControls value={draft} onChange={setDraft} idPrefix="rerank" columns={2} />
          </div>
          <p className="mt-3 text-[12.5px]" style={{ color: C.muted2 }}>
            Preferred publishers: {publishersPhrase(savedPublishers)}.
            {!samePublishers(savedPublishers, runPreferred) && ` This run preferred ${publishersPhrase(runPreferred)}; re-ranking uses yours.`}{" "}
            <Link href="/settings#discovery" className="underline underline-offset-4 hover:text-white" style={{ color: C.muted }}>
              Change them in Settings
            </Link>
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={rerank}
              disabled={
                reranking || criteriaError(draft) !== null || (ranked !== null && sameCriteria(draft, ranked) && samePublishers(savedPublishers, runPreferred))
              }
              className="rounded-full px-4 py-2 text-sm font-semibold disabled:opacity-50"
              style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
            >
              {reranking ? "Re-ranking…" : "Re-rank results"}
            </button>
            {!sameCriteria(draft, DEFAULT_CRITERIA) && (
              <button
                type="button"
                onClick={() => setDraft(DEFAULT_CRITERIA)}
                className="rounded-full px-4 py-2 text-sm font-semibold hover:bg-white/10"
                style={{ border: `1px solid ${C.lineStrong}` }}
              >
                Back to the default weights
              </button>
            )}
            {rerankError && (
              <p role="alert" className="flex items-center gap-1.5 text-sm" style={{ color: C.danger }}>
                <WarningCircle className="size-4" weight="bold" aria-hidden />
                {rerankError}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs" style={{ color: C.muted2 }}>
        <span aria-live="polite">
          {filtering ? `${visible.length} of ${related.results.length} papers` : `${related.results.length} papers`}
          {filtering && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setBand("all");
                setFoundBy("all");
                setPublisher("all");
              }}
              className="ml-2 underline underline-offset-2 hover:text-white"
            >
              Clear filters
            </button>
          )}
        </span>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Score bar colours">
          {CRITERIA.map(({ key, label }) => (
            <span key={key} className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-sm" style={{ background: CRITERION_COLOR[key] }} aria-hidden />
              {label}
            </span>
          ))}
        </span>
      </div>

      {related.results.length === 0 ? (
        <div className="mt-4 rounded-2xl px-6 py-14 text-center" style={{ background: C.glass, border: `1px dashed ${C.lineStrong}` }}>
          <p className="text-base font-semibold">No related papers found</p>
          <p className="mt-2 text-sm" style={{ color: C.muted }}>
            Try again later, or broaden the seed paper&apos;s profile.
          </p>
        </div>
      ) : (
        <div className="mt-2 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,27rem)]">
          <div className="rounded-2xl" style={{ background: C.glass, border: `1px solid ${C.line}` }}>
            {visible.length === 0 ? (
              <div className="px-6 py-14 text-center">
                <p className="text-base font-semibold">No results match these filters</p>
                <p className="mt-2 text-sm" style={{ color: C.muted }}>
                  Clear the filters to see all {related.results.length} papers.
                </p>
              </div>
            ) : (
              <ul
                ref={listRef}
                onKeyDown={onListKey}
                aria-label="Ranked results; arrow keys move between papers"
                className="max-h-[calc(100dvh-13rem)] divide-y divide-white/[0.06] overflow-y-auto overscroll-contain"
                data-testid="results-list"
              >
                {visible.map((r, i) => (
                  <ResultRow
                    key={r.paper.id}
                    result={r}
                    index={i}
                    focused={focused?.paper.id === r.paper.id}
                    selected={selected.has(r.paper.id)}
                    onFocus={() => setFocusedId(r.paper.id)}
                    onToggle={() => onToggle(r.paper.id)}
                  />
                ))}
              </ul>
            )}
          </div>
          <aside
            aria-label="The paper in focus"
            className="max-h-[calc(100dvh-13rem)] overflow-y-auto overscroll-contain rounded-2xl px-5 py-5 lg:sticky lg:top-4"
            style={{ background: C.glass2, border: `1px solid ${C.line}` }}
          >
            {focused ? (
              <RankDetail result={focused} run={related.run} selected={selected.has(focused.paper.id)} onToggle={() => onToggle(focused.paper.id)} />
            ) : (
              <p className="text-sm" style={{ color: C.muted }}>
                Choose a paper to see why it ranks where it does.
              </p>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
