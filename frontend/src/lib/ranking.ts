/**
 * The ranking criteria a researcher sets (remediation Phase 9; the preferred
 * publisher added 2026-10-02) and the
 * real ranking decision behind each result. The criteria are sent with a
 * discovery run and to a re-rank; the backend turns them into the fusion
 * weights (app/domain/ranking.py RankingCriteria) -- nothing here ranks.
 */
"use client";

import { useSyncExternalStore } from "react";
import type { Confidence, RankingCriteria, RankingExplanation, SignalName } from "@/lib/api/types";

export type CriterionKey = keyof RankingCriteria;

export const CRITERIA: { key: CriterionKey; label: string; hint: string }[] = [
  { key: "topic", label: "Topic similarity", hint: "How close the paper's text is to the seed, as a whole and passage by passage" },
  { key: "problem", label: "Research problem", hint: "How close it is to the seed's research problem" },
  { key: "methods", label: "Methods", hint: "How close it is to the methods the seed uses" },
  { key: "datasets", label: "Datasets", hint: "Whether it names the datasets the seed uses" },
  { key: "citations", label: "Citation links", hint: "Whether it cites the seed or the seed cites it" },
  { key: "recency", label: "Recency", hint: "How recent it is relative to the seed" },
  { key: "publisher", label: "Preferred publisher", hint: "Published by IEEE, Springer, ACM or Elsevier" },
];

/** The defaults (backend RankingCriteria): the initial weights, plus a
 * preference for IEEE, Springer, ACM and Elsevier papers. */
export const DEFAULT_CRITERIA: RankingCriteria = { topic: 42, problem: 18, methods: 14, datasets: 8, citations: 12, recency: 6, publisher: 15 };

/** The initial weights, before the publisher preference existed: how runs
 * ranked before 2026-10-02 were weighed. */
export const INITIAL_CRITERIA: RankingCriteria = { ...DEFAULT_CRITERIA, publisher: 0 };

/** How a set of criteria is named on the page. */
export function criteriaName(c: RankingCriteria): string {
  if (sameCriteria(c, DEFAULT_CRITERIA)) return "the default weights";
  if (sameCriteria(c, INITIAL_CRITERIA)) return "the initial weights";
  return "your weights";
}

/** Which criterion each computed signal stands for, and its own name. */
export const SIGNALS: Record<SignalName, { criterion: CriterionKey; label: string }> = {
  semantic_doc: { criterion: "topic", label: "Topic similarity (whole paper)" },
  semantic_chunk: { criterion: "topic", label: "Topic similarity (passages)" },
  problem_sim: { criterion: "problem", label: "Research problem" },
  method_sim: { criterion: "methods", label: "Methods" },
  dataset_overlap: { criterion: "datasets", label: "Datasets" },
  citation: { criterion: "citations", label: "Citation link to the seed" },
  recency: { criterion: "recency", label: "Recency" },
  publisher: { criterion: "publisher", label: "Preferred publisher" },
};

/** One fixed hue per criterion, in this order (validated as a set on the
 * dark surface: CVD and normal-vision separation, 3:1 contrast). A colour
 * always travels with its criterion's name. */
export const CRITERION_COLOR: Record<CriterionKey, string> = {
  topic: "#3987e5",
  problem: "#d95926",
  methods: "#199e70",
  datasets: "#c98500",
  citations: "#d55181",
  recency: "#008300",
  publisher: "#9085e9",
};

export function criteriaError(c: RankingCriteria): string | null {
  const values = CRITERIA.map(({ key }) => c[key]);
  if (values.some((v) => !Number.isInteger(v) || v < 0 || v > 100)) return "Each criterion is a whole number from 0 to 100.";
  if (values.every((v) => v === 0)) return "At least one criterion has to count.";
  return null;
}

/** Each criterion's share of the weighting, in whole percent. */
export function criteriaShares(c: RankingCriteria): Record<CriterionKey, number> {
  const total = CRITERIA.reduce((sum, { key }) => sum + c[key], 0);
  return Object.fromEntries(CRITERIA.map(({ key }) => [key, total > 0 ? Math.round((c[key] / total) * 100) : 0])) as Record<
    CriterionKey,
    number
  >;
}

export function sameCriteria(a: RankingCriteria, b: RankingCriteria): boolean {
  return CRITERIA.every(({ key }) => a[key] === b[key]);
}

// -- kept in this browser -------------------------------------------------------

const KEY = "researchnexus.pref.rankingCriteria";
const EVENT = "researchnexus:ranking-criteria";

export function readCriteria(): RankingCriteria {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return DEFAULT_CRITERIA;
    const parsed = JSON.parse(raw) as Partial<RankingCriteria>;
    // criteria saved before a criterion existed take its default
    const c = Object.fromEntries(CRITERIA.map(({ key }) => [key, parsed[key] ?? DEFAULT_CRITERIA[key]])) as unknown as RankingCriteria;
    return criteriaError(c) === null ? c : DEFAULT_CRITERIA;
  } catch {
    return DEFAULT_CRITERIA; // unreadable or storage blocked: the defaults, quietly
  }
}

export function writeCriteria(c: RankingCriteria): boolean {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(c));
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(EVENT));
  return true;
}

let cached: { raw: string | null; value: RankingCriteria } | null = null;

function snapshot(): RankingCriteria {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    raw = null;
  }
  if (!cached || cached.raw !== raw) cached = { raw, value: readCriteria() };
  return cached.value;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The criteria saved in this browser (the defaults until changed). */
export function useSavedCriteria(): RankingCriteria {
  return useSyncExternalStore(subscribe, snapshot, () => DEFAULT_CRITERIA);
}

// -- why a paper ranks where it does ----------------------------------------------

export interface RankRow {
  signal: SignalName;
  label: string;
  criterion: CriterionKey;
  value: number;
  weight: number;
  contribution: number;
  /** share of the paper's score, whole percent */
  share: number;
}

/** The ranking decision for one paper: what each computed signal added to its
 * score (largest first), and the signals that couldn't be computed for it.
 * Empty for a ranking saved before contributions were kept. */
export function explainRank(explanation: RankingExplanation, fusedScore: number): { rows: RankRow[]; missing: string[] } {
  const rows = (explanation.contributions ?? []).map((c) => ({
    signal: c.signal,
    label: SIGNALS[c.signal]?.label ?? c.signal,
    criterion: SIGNALS[c.signal]?.criterion ?? "topic",
    value: c.value,
    weight: c.weight,
    contribution: c.contribution,
    share: fusedScore > 0 ? Math.round((c.contribution / fusedScore) * 100) : 0,
  }));
  const missing = (explanation.missing_signals ?? []).map((s) => SIGNALS[s]?.label ?? s);
  return { rows, missing };
}

export function bandReason(score: number, band: Confidence, bands: { high: number; medium: number }): string {
  const s = score.toFixed(2);
  if (band === "high") return `Score ${s}: high starts at ${bands.high.toFixed(2)}.`;
  if (band === "medium") return `Score ${s}: medium is ${bands.medium.toFixed(2)} up to ${bands.high.toFixed(2)}.`;
  return `Score ${s}: low is below ${bands.medium.toFixed(2)}.`;
}
