import type { ProfileField, ProfileList, ProvenanceStatus, ResearchProfile } from "@/lib/api/types";

/**
 * A research profile, read for the page (remediation Phase 6).
 *
 * The backend has already cleaned and deduplicated the profile and found
 * each metric's value in its evidence; this only decides what is shown
 * where, and says plainly what is missing. Nothing here invents a value.
 */

export interface ProfileItem {
  key: string;
  text: string;
  status: ProvenanceStatus;
  quote: string | null;
  page: number | null;
}

/** A quote as the eye reads it: a word broken across a PDF line joined again. */
export function cleanQuote(quote: string): string {
  return quote
    .replace(/(\w)-[ \t]*\n[ \t]*(\w)/g, "$1$2")
    .replace(/\s+/g, " ")
    .trim();
}

function item(field: ProfileField, key: string): ProfileItem {
  const quote = field.source_span?.quote ? cleanQuote(field.source_span.quote) : null;
  return { key, text: field.value.trim(), status: field.status, quote, page: field.source_span?.page ?? null };
}

export function itemsOf(list: ProfileList | undefined, prefix: string): ProfileItem[] {
  return (list?.items ?? []).filter((f) => f.value.trim()).map((f, i) => item(f, `${prefix}-${i}`));
}

export function fieldOf(field: ProfileField | undefined, key: string): ProfileItem | null {
  return field && field.value.trim() ? item(field, key) : null;
}

// --- the abstract, in brief -----------------------------------------------------

export interface Brief {
  /** What to read first: the summary, or the abstract itself when it is short. */
  summary: string;
  /** The full abstract, when it says more than the summary. */
  fullAbstract: string | null;
  /** False when the paper had no abstract and its stand-in text must not be shown as one. */
  abstractFound: boolean;
}

export function briefOf(profile: Pick<ResearchProfile, "abstract" | "summary" | "abstract_found">): Brief {
  const abstractFound = profile.abstract_found !== false;
  if (!abstractFound) return { summary: "", fullAbstract: null, abstractFound };
  const abstract = profile.abstract.trim();
  const summary = profile.summary?.trim() || abstract; // a profile served before summaries existed
  return { summary, fullAbstract: abstract && abstract !== summary ? abstract : null, abstractFound };
}

export function groundingNote(profile: Pick<ResearchProfile, "grounding">): string {
  return profile.grounding === "abstract" ? "Read from the abstract only" : "Read from the full text";
}

// --- metrics, with the value each is reported at ----------------------------------

export type MetricState = "reported" | "unconfirmed" | "not_reported";

export interface MetricRow extends ProfileItem {
  /** The paper's own figure, only when it is written in the metric's evidence. */
  value: string | null;
  state: MetricState;
}

export function metricRows(profile: Pick<ResearchProfile, "evaluation_metrics">): MetricRow[] {
  return (profile.evaluation_metrics?.items ?? [])
    .filter((f) => f.value.trim())
    .map((f, i) => {
      const reported = f.reported_value;
      const state: MetricState = !reported ? "not_reported" : reported.status === "verified" ? "reported" : "unconfirmed";
      return { ...item(f, `metric-${i}`), value: state === "reported" ? reported!.text : null, state };
    });
}

export const METRIC_STATE_TEXT: Record<Exclude<MetricState, "reported">, string> = {
  not_reported: "No value in the evidence",
  unconfirmed: "Value not confirmed in the text",
};

// --- sections -------------------------------------------------------------------

export interface Group {
  label: string;
  items: ProfileItem[];
}

function groups(entries: [string, ProfileItem[]][]): Group[] {
  return entries.filter(([, items]) => items.length > 0).map(([label, items]) => ({ label, items }));
}

/** How the paper does it: the named things it uses. */
export function approachGroups(profile: ResearchProfile): Group[] {
  return groups([
    ["Methods", itemsOf(profile.methods, "method")],
    ["Models", itemsOf(profile.models, "model")],
    ["Algorithms", itemsOf(profile.algorithms, "algorithm")],
    ["Datasets", itemsOf(profile.datasets, "dataset")],
  ]);
}

/** Where the paper sits and what it mentions: useful, but not the first read. */
export function contextGroups(profile: ResearchProfile): Group[] {
  const domain = fieldOf(profile.domain, "domain");
  return groups([
    ["Field", domain ? [domain] : []],
    ["Subfields", itemsOf(profile.subdomains, "subdomain")],
    ["Methods it cites", itemsOf(profile.cited_methods, "cited")],
    ["Also mentioned", itemsOf(profile.important_entities, "entity")],
  ]);
}

/** Whether any item couldn't be matched to the paper's text. */
export function hasUnmatched(profile: ResearchProfile): boolean {
  const lists: (ProfileList | undefined)[] = [
    profile.subdomains, profile.research_questions, profile.objectives, profile.methods, profile.models, profile.algorithms,
    profile.datasets, profile.evaluation_metrics, profile.findings, profile.limitations, profile.future_work,
    profile.important_entities, profile.cited_methods,
  ];
  const fields = [profile.domain, profile.research_problem, ...lists.flatMap((l) => l?.items ?? [])];
  return fields.some((f) => f && f.value.trim() && f.status === "unverified");
}
