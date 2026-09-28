import type { LlmProvider, UsageRange, UsageReport, UsageTotals } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/time";

/**
 * Model usage, read and worded one way (remediation Phase 5).
 *
 * Every number is the provider's own token count, summed by the backend from
 * the calls a user's keys made. There is no cost anywhere: no provider says
 * what a call cost, and with the user's own key the price depends on their
 * plan, free quota and discounts -- none of which ResearchNexus can see.
 */

export const RANGES: { key: UsageRange; label: string }[] = [
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
  { key: "all", label: "All time" },
];

const FEATURES: Record<string, string> = {
  chat: "Chat",
  rag: "Chat answers",
  gaps: "Research gaps",
  directions: "Research directions",
  comparison: "Comparison",
  profile: "Paper profiles",
  discovery: "Discovery search plans",
  summary: "Summaries",
  keypoints: "Key points",
  other: "Unlabelled",
};

/** What a call was for, in the app's own words. */
export function featureLabel(feature: string): string {
  return FEATURES[feature] ?? feature.charAt(0).toUpperCase() + feature.slice(1).replaceAll("_", " ");
}

/** Why a row is called what it is, when its name alone can't say. */
export function featureHint(feature: string): string | undefined {
  if (feature === "other") return "Calls recorded before each call was labelled with what it was for.";
  if (feature === "profile") return "Reading a paper into its research profile.";
  if (feature === "discovery") return "Planning the searches for related papers.";
  return undefined;
}

const exact = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** "48,210": every token, for tables. */
export const formatTokens = (n: number): string => exact.format(n);

/** "48.2K": a glance, for a header. Exact below ten thousand. */
export const compactTokens = (n: number): string => (n < 10_000 ? exact.format(n) : compact.format(n));

export const plural = (n: number, one: string, many = `${one}s`): string => `${exact.format(n)} ${n === 1 ? one : many}`;

/** A part's share of a whole, 0 to 1 (0 when the whole is nothing). */
export function shareOf(part: number, whole: number): number {
  return whole > 0 ? Math.min(1, Math.max(0, part / whole)) : 0;
}

/**
 * The range a report covers, in words: "Last 30 days, since Aug 29" or
 * "All time, since Sep 27" (its first call). `exact` is the start to the
 * minute, for a tooltip.
 */
export function rangeLabel(report: Pick<UsageReport, "range" | "first_call_at">, options: { timeZone?: string; locale?: string; now?: number } = {}): {
  text: string;
  exact: string | null;
} {
  const { range, first_call_at } = report;
  if (range.since === null) {
    return first_call_at
      ? { text: `All time, since ${formatDate(first_call_at, options)}`, exact: formatDateTime(first_call_at, options) }
      : { text: "All time", exact: null };
  }
  const label = RANGES.find((r) => r.key === range.key)?.label ?? `${range.days} days`;
  return { text: `Last ${label}, since ${formatDate(range.since, options)}`, exact: formatDateTime(range.since, options) };
}

/** What the totals leave out or fold in, said plainly. Empty when nothing needs saying. */
export function usageCaveats(totals: UsageTotals): string[] {
  const out: string[] = [];
  if (totals.failed_calls > 0) {
    out.push(`${plural(totals.failed_calls, "call")} failed and reported no tokens; ${totals.failed_calls === 1 ? "it is" : "they are"} counted as calls only.`);
  }
  if (totals.unreported_calls > 0) {
    out.push(
      `${plural(totals.unreported_calls, "answered call")} came back without usage from the provider, so ${totals.unreported_calls === 1 ? "its" : "their"} tokens are missing from these totals.`,
    );
  }
  return out;
}

/** Where each provider shows what a user was actually billed. */
export const CONSOLES: Record<LlmProvider, { name: string; url: string }> = {
  deepseek: { name: "DeepSeek", url: "https://platform.deepseek.com" },
  openai: { name: "OpenAI", url: "https://platform.openai.com/usage" },
  groq: { name: "Groq", url: "https://console.groq.com" },
  openrouter: { name: "OpenRouter", url: "https://openrouter.ai/activity" },
  together: { name: "Together", url: "https://api.together.ai" },
  gemini: { name: "Gemini", url: "https://aistudio.google.com" },
};

/** The consoles of the providers a report used, in the order they were used most. */
export function billingConsoles(report: Pick<UsageReport, "by_model">): { name: string; url: string }[] {
  const seen = new Set<string>();
  const out: { name: string; url: string }[] = [];
  for (const row of report.by_model) {
    const console = CONSOLES[row.provider as LlmProvider];
    if (console && !seen.has(row.provider)) {
      seen.add(row.provider);
      out.push(console);
    }
  }
  return out;
}
