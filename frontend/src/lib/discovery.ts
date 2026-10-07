/**
 * What a discovery run is doing, and what a finished one is missing
 * (remediation Phase 8) -- worded from the job's live progress and the saved
 * run's report (backend app/services/discovery/progress.py). Nothing here is
 * estimated: counts are real answers, times are measured, and the only
 * countdown shown is the limit the backend itself enforces on a step.
 */
import type {
  DiscoveryProgress,
  DiscoveryReport,
  DiscoveryStep,
  DiscoveryStepEntry,
  DiscoveryStrategy,
  DiscoveryStrategyEntry,
  DiscoverySourceEntry,
  Job,
} from "@/lib/api/types";

export const STEP_ORDER: DiscoveryStep[] = ["plan", "resolve", "search", "score", "save", "rank", "trail"];

export const STEP_LABEL: Record<DiscoveryStep, string> = {
  plan: "Search plan",
  resolve: "Find the seed",
  search: "Search sources",
  score: "Score against the seed",
  save: "Save candidates",
  rank: "Rank",
  trail: "Relationships",
};

/** The strategies that search, in the order the page lists them. */
export const SEARCH_STRATEGIES: DiscoveryStrategy[] = ["keyword", "query_expansion", "citation", "recommendation"];
const STRATEGY_ORDER: DiscoveryStrategy[] = [...SEARCH_STRATEGIES, "semantic", "semantic_doc"];

export const STRATEGY_LABEL: Partial<Record<DiscoveryStrategy, string>> = {
  keyword: "Keyword search",
  query_expansion: "Expanded queries",
  citation: "Citations",
  recommendation: "Recommendations",
  semantic: "Passage similarity",
  semantic_doc: "Paper similarity",
};

export const SOURCE_LABEL: Record<string, string> = {
  openalex: "OpenAlex",
  semantic_scholar: "Semantic Scholar",
  arxiv: "arXiv",
  europe_pmc: "Europe PMC",
  crossref: "Crossref",
};
export const SOURCE_ORDER = ["openalex", "arxiv", "europe_pmc", "semantic_scholar", "crossref"];

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** A discover job's structured progress, or null for an older (or mocked)
 * job that only names its stage. */
export function discoveryProgress(progress: unknown): DiscoveryProgress | null {
  if (!isRecord(progress) || !isRecord(progress.steps)) return null;
  return {
    stage: typeof progress.stage === "string" ? progress.stage : "discovery",
    step: (typeof progress.step === "string" ? progress.step : "") as DiscoveryProgress["step"],
    started_at: typeof progress.started_at === "string" ? progress.started_at : "",
    elapsed_s: typeof progress.elapsed_s === "number" ? progress.elapsed_s : 0,
    steps: progress.steps as DiscoveryProgress["steps"],
    strategies: (isRecord(progress.strategies) ? progress.strategies : {}) as DiscoveryProgress["strategies"],
    sources: (isRecord(progress.sources) ? progress.sources : {}) as DiscoveryProgress["sources"],
    found: typeof progress.found === "number" ? progress.found : 0,
    preview: Array.isArray(progress.preview) ? (progress.preview as DiscoveryProgress["preview"]) : [],
    warnings: Array.isArray(progress.warnings) ? (progress.warnings as string[]) : [],
  };
}

export type RunState = "starting" | "running" | "done" | "failed" | "cancelled" | "interrupted";

export function runState(job: Job | undefined): RunState {
  if (!job) return "starting";
  switch (job.status) {
    case "succeeded":
    case "partial":
      return "done";
    case "cancelled":
      return "cancelled";
    case "failed":
      return job.progress?.stage === "interrupted" ? "interrupted" : "failed";
    default:
      return "running";
  }
}

const STEP_HEADLINE: Record<DiscoveryStep, string> = {
  plan: "Writing the search plan…",
  resolve: "Looking the seed paper up on OpenAlex and Semantic Scholar…",
  search: "Searching external sources…",
  score: "Scoring candidates against the seed…",
  save: "Saving candidates…",
  rank: "Ranking candidates against the seed profile…",
  trail: "Classifying relationships…",
};

/** One line on what the run is doing now. */
export function headline(progress: DiscoveryProgress | null, stage: string | undefined): string {
  if (progress?.step) return STEP_HEADLINE[progress.step];
  switch (stage) {
    case "discovery":
      return STEP_HEADLINE.search;
    case "ranking":
      return STEP_HEADLINE.rank;
    case "trail":
      return STEP_HEADLINE.trail;
    case "done":
      return "Done.";
    default:
      return "Starting…";
  }
}

export function formatSeconds(s: number): string {
  if (s < 60) return `${Math.round(s * 10) / 10} s`;
  const whole = Math.round(s);
  return `${Math.floor(whole / 60)} min ${whole % 60} s`;
}

/** A finished step's measured time; a running step's time left before the
 * limit the backend enforces on it (never an estimate of when it will end). */
export function stepTiming(entry: DiscoveryStepEntry, elapsedS: number): string | null {
  if ((entry.state === "done" || entry.state === "failed") && entry.seconds != null) return formatSeconds(entry.seconds);
  if (entry.state === "running" && entry.limit_s != null && entry.started_s != null) {
    const left = entry.limit_s - (elapsedS - entry.started_s);
    return left > 0.5 ? `stops within ${Math.ceil(left)} s` : "stopping";
  }
  return null;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** What a step has produced, in a few words. */
export function stepDetail(step: DiscoveryStep, entry: DiscoveryStepEntry, foundSoFar: number): string | null {
  if (entry.state === "failed" || entry.state === "skipped") return entry.note ? capitalise(entry.note) : null;
  switch (step) {
    case "plan":
      if (entry.state !== "done") return null;
      return entry.note === "model" ? "Written by your model" : "Built from the paper's profile";
    case "resolve":
      return entry.note ? capitalise(entry.note) : null;
    case "search":
      if (entry.state === "running") return `${plural(foundSoFar, "paper")} so far`;
      return entry.found != null ? `${plural(entry.found, "paper")} found` : null;
    case "score":
      return entry.total != null ? `${plural(entry.total, "record")} of the papers kept` : null;
    case "save":
      return entry.state === "done" && entry.total != null ? `${plural(entry.total, "candidate")} saved` : null;
    case "rank":
      if (entry.state !== "done" || entry.ranked == null) return null;
      return `${entry.ranked} ranked${entry.off_topic ? ` · ${entry.off_topic} set aside as off-topic` : ""}`;
    case "trail":
      return entry.state === "done" && entry.edges != null ? `${plural(entry.edges, "connection")} proposed` : null;
  }
}

const NOTE_PHRASE: [RegExp, string][] = [
  [/_no_seed_id$/, "Nothing to start from: the seed wasn't found on OpenAlex or Semantic Scholar"],
  [/_all_sources_failed$/, "Every source it asked failed"],
  [/_no_queries$/, "It had no queries to run"],
  [/_no_embedder$/, "No relevance model was loaded"],
  [/^citation_cites_seed_failed$/, "Couldn't fetch the papers citing the seed"],
  [/^citation_cited_by_seed_failed$/, "Couldn't fetch the seed's references"],
  [/^citation_lookup_failed$/, "Couldn't look the seed up on OpenAlex"],
  [/^recommendation_s2_failed$/, "Semantic Scholar's recommendations failed"],
  [/^recommendation_openalex_failed$/, "OpenAlex's related works failed"],
  [/_external_budget$/, "It reached the run's limit on requests"],
];

/** Why a strategy found what it did, when that needs saying. */
export function strategyNote(name: DiscoveryStrategy, entry: DiscoveryStrategyEntry): string | null {
  const notes = entry.notes ?? [];
  if (entry.state === "timed_out") {
    const limit = entry.seconds != null ? `its ${formatSeconds(entry.seconds)} limit` : "its time limit";
    return `Stopped at ${limit}; the ${plural(entry.found, "paper")} it had found are kept`;
  }
  if (entry.state === "failed") {
    return notes.some((n) => n.endsWith("_timed_out")) ? "Ran out of time before anything came back" : "It failed";
  }
  const phrases = notes.flatMap((n) => {
    const hit = NOTE_PHRASE.find(([pattern]) => pattern.test(n));
    if (hit) return [hit[1]];
    const unanswered = /_unanswered:(\d+)$/.exec(n);
    return unanswered ? [`${plural(Number(unanswered[1]), "request")} went unanswered`] : [];
  });
  if (phrases.length > 0) return [...new Set(phrases)].join("; ");
  return entry.state === "done" && entry.found === 0 ? "Nothing found" : null;
}

export function failureWord(code: string | undefined): string {
  if (!code) return "failed";
  if (code === "rate_limited") return "rate-limited";
  if (code === "unreachable") return "unreachable";
  if (code === "http_404") return "not found";
  const http = /^http_(\d{3})$/.exec(code);
  if (http) return Number(http[1]) >= 500 ? `unavailable, HTTP ${http[1]}` : `HTTP ${http[1]}`;
  return code;
}

export function sourceSummary(entry: DiscoverySourceEntry): string {
  const parts: string[] = [];
  if (entry.answered > 0 || (entry.failed === 0 && entry.cached === 0)) parts.push(`${entry.answered} answered`);
  if (entry.cached > 0) parts.push(`${entry.cached} reused`);
  if (entry.failed > 0) parts.push(`${entry.failed} refused (${failureWord(entry.last_failure)})`);
  return parts.join(" · ");
}

const PLAN_FALLBACK: Record<string, string> = {
  search_plan_fallback_timeout: "The model took too long to write the search plan, so the plan built from the paper's profile was used.",
  search_plan_fallback_llm_error: "The model couldn't write the search plan, so the plan built from the paper's profile was used.",
  search_plan_fallback_key_unusable: "Your saved model key couldn't be read, so the plan built from the paper's profile was used.",
};

export interface RunIssues {
  /** what a partial run is missing, and why */
  incomplete: string[];
  /** worth knowing, but nothing is missing */
  notes: string[];
}

/** What a saved run did not finish, from its own report. */
export function runIssues(report: DiscoveryReport, counts: { after_dedupe: number }): RunIssues {
  const incomplete: string[] = [];
  const notes: string[] = [];
  for (const name of STRATEGY_ORDER) {
    const entry = report.strategies[name];
    const label = STRATEGY_LABEL[name] ?? name;
    if (entry?.state === "failed") incomplete.push(`${label} failed.`);
    if (entry?.state === "timed_out") {
      const after = entry.seconds != null ? ` after ${formatSeconds(entry.seconds)}` : "";
      incomplete.push(`${label} ran out of time${after}; the ${plural(entry.found, "paper")} it had found are included.`);
    }
  }
  for (const source of SOURCE_ORDER) {
    const entry = report.sources[source];
    if (entry && entry.failed > 0) {
      incomplete.push(
        `${SOURCE_LABEL[source] ?? source} refused ${entry.failed} of ${entry.answered + entry.failed} requests (${failureWord(entry.last_failure)}).`,
      );
    }
  }
  for (const warning of report.warnings) if (PLAN_FALLBACK[warning]) incomplete.push(PLAN_FALLBACK[warning]);

  const resolve = report.steps.resolve;
  if (resolve?.state === "failed") incomplete.push("The seed couldn't be looked up, so citations and recommendations had nothing to start from.");
  else if (resolve?.note?.startsWith("not found")) {
    notes.push("The seed isn't on OpenAlex or Semantic Scholar, so it had no citations or recommendations to follow.");
  }
  const saved = report.steps.save?.total;
  if (report.warnings.includes("budget_truncated") && saved != null) {
    notes.push(`Kept the ${saved} papers with the most evidence of the ${counts.after_dedupe} found; the rest weren't ranked.`);
  }
  return { incomplete, notes };
}
