import type { Confidence, DirectionKind, DirectionUserState, DirectionsGenerateResponse, ResearchDirection, ResearchGap } from "@/lib/api/types";

export const KIND_COPY: Record<DirectionKind, { label: string; long: string; meaning: string }> = {
  evidence_backed_inference: {
    label: "Evidence-backed",
    long: "Evidence-backed inference",
    meaning: "Its method and data are already named by the gap and its passages; it follows from them.",
  },
  llm_hypothesis: {
    label: "Hypothesis",
    long: "Model hypothesis",
    meaning: "It proposes a method or data the gap's evidence doesn't name: an idea to test, not a finding.",
  },
};

export function kindOf(d: ResearchDirection): DirectionKind {
  return d.kind === "llm_hypothesis" ? "llm_hypothesis" : "evidence_backed_inference";
}

export const STATE_LABEL: Record<DirectionUserState, string> = {
  candidate: "To review",
  accepted: "Accepted",
  rejected: "Rejected",
};

/** The bands of app/services/directions/confidence.py::assign_confidence. */
export const CONFIDENCE_MEANING: Record<Confidence, string> = {
  high: "Evidence-backed, well grounded (4+) and specific (3+), from a high- or medium-confidence gap.",
  medium: "Reasonably grounded (3+) and specific (2+).",
  low: "Weakly grounded or vague, or its gap's statement isn't supported by its own evidence.",
};

export interface CritiqueAxis {
  key: "groundedness" | "specificity" | "novelty" | "feasibility";
  label: string;
  meaning: string;
  score: number | null;
  /** The most this axis can score (feasibility is never claimed high). */
  cap: number;
}

const AXES: Omit<CritiqueAxis, "score">[] = [
  { key: "groundedness", label: "Grounded", meaning: "How well its motivation follows from the gap's evidence.", cap: 5 },
  { key: "specificity", label: "Specific", meaning: "How concrete and actionable it is.", cap: 5 },
  { key: "novelty", label: "Novel", meaning: "How fresh the idea is.", cap: 5 },
  { key: "feasibility", label: "Feasible", meaning: "How practical it looks. Always uncertain, so never scored above 3.", cap: 3 },
];

/** The critique's four 1-5 scores, in reading order; a missing one is null. */
export function critiqueAxes(d: ResearchDirection): CritiqueAxis[] {
  return AXES.map((a) => {
    const v = d.critique[a.key];
    return { ...a, score: typeof v === "number" && Number.isFinite(v) ? Math.max(1, Math.min(5, Math.round(v))) : null };
  });
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Why a direction has its band, read from `confidence_basis` (never a made-up percentage). */
export function directionReasons(d: ResearchDirection): string[] {
  const b = d.confidence_basis;
  const out: string[] = [];
  out.push(
    kindOf(d) === "evidence_backed_inference"
      ? "Evidence-backed: its method and data come from the gap itself"
      : "A hypothesis: it proposes something the gap's evidence doesn't name",
  );
  const grounded = num(b.groundedness) ?? num(d.critique.groundedness);
  const specific = num(b.specificity) ?? num(d.critique.specificity);
  if (grounded != null && specific != null) out.push(`Grounded ${grounded} of 5, specific ${specific} of 5 in the critique`);
  if (typeof b.gap_confidence === "string") out.push(`It rests on a ${b.gap_confidence}-confidence gap`);
  if (b.gap_self_support === false) out.push("Its gap's statement was not confirmed by its own evidence");
  if (b.low_critique === true || d.flags.includes("low_critique")) out.push("The critique scored it 2 or lower on at least one axis");
  return out;
}

export interface DirectionFilters {
  state: DirectionUserState | "all";
  kind: DirectionKind | "all";
  query: string;
}

export const NO_FILTERS: DirectionFilters = { state: "candidate", kind: "all", query: "" };

const fold = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");

/** Search its own words, its plan, its gap's statement, and the passages behind it. */
export function directionMatches(d: ResearchDirection, query: string, gapStatement = "", paperTitles: Record<string, string> = {}): boolean {
  const q = fold(query.trim());
  if (!q) return true;
  const hay = [
    d.proposal,
    d.motivation,
    d.suggested_method,
    d.possible_dataset ?? "",
    d.evaluation_strategy,
    ...d.risks,
    KIND_COPY[kindOf(d)].label,
    gapStatement,
    ...d.supporting_evidence.map((e) => e.span.quote),
    ...d.related_papers.map((p) => paperTitles[p] ?? ""),
  ]
    .map(fold)
    .join("\n");
  return q.split(/\s+/).every((t) => hay.includes(t));
}

const RANK: Record<Confidence, number> = { high: 0, medium: 1, low: 2 };

/** Strongest first: band, then evidence-backed before hypotheses, then the proposal. */
export function sortDirections(ds: ResearchDirection[]): ResearchDirection[] {
  return [...ds].sort(
    (a, b) =>
      RANK[a.confidence] - RANK[b.confidence] ||
      Number(kindOf(a) === "llm_hypothesis") - Number(kindOf(b) === "llm_hypothesis") ||
      a.proposal.localeCompare(b.proposal),
  );
}

export function filterDirections(
  ds: ResearchDirection[],
  f: DirectionFilters,
  gapStatements: Record<string, string> = {},
  paperTitles: Record<string, string> = {},
): ResearchDirection[] {
  return ds.filter(
    (d) =>
      (f.state === "all" || d.user_state === f.state) &&
      (f.kind === "all" || kindOf(d) === f.kind) &&
      directionMatches(d, f.query, gapStatements[d.gap_id] ?? "", paperTitles),
  );
}

export function countByState(ds: ResearchDirection[]): Record<DirectionUserState | "all", number> {
  const out = { candidate: 0, accepted: 0, rejected: 0, all: ds.length };
  for (const d of ds) out[d.user_state] += 1;
  return out;
}

export interface GapGroup {
  gapId: string;
  gap: ResearchGap | null;
  directions: ResearchDirection[];
}

/** Directions under the gap each one comes from: gaps in the gaps' own
 * order (accepted ones first), a gap's directions strongest first. */
export function groupByGap(ds: ResearchDirection[], gaps: ResearchGap[]): GapGroup[] {
  const byGap = new Map<string, ResearchDirection[]>();
  for (const d of ds) byGap.set(d.gap_id, [...(byGap.get(d.gap_id) ?? []), d]);
  const known = [...gaps].sort((a, b) => Number(b.user_state === "accepted") - Number(a.user_state === "accepted"));
  const order = [...known.map((g) => g.gap_id).filter((id) => byGap.has(id)), ...[...byGap.keys()].filter((id) => !gaps.some((g) => g.gap_id === id))];
  return order.map((gapId) => ({ gapId, gap: gaps.find((g) => g.gap_id === gapId) ?? null, directions: sortDirections(byGap.get(gapId)!) }));
}

/** What a run did with every gap and every proposal, in plain sentences. */
export function generationOutcome(res: DirectionsGenerateResponse): { headline: string; notes: string[] } {
  const gapsRead = res.requested - res.skipped_not_accepted - res.skipped_not_found;
  const headline =
    res.generated === 0
      ? "No direction survived this run."
      : `Proposed ${res.generated} direction${res.generated === 1 ? "" : "s"} from ${gapsRead} gap${gapsRead === 1 ? "" : "s"}.`;
  const notes: string[] = [];
  if (res.dropped_unsupported > 0)
    notes.push(
      `${res.dropped_unsupported} ${res.dropped_unsupported === 1 ? "proposal was" : "proposals were"} dropped for naming something the gap's evidence doesn't contain.`,
    );
  if (res.skipped_not_accepted > 0)
    notes.push(`${res.skipped_not_accepted} gap${res.skipped_not_accepted === 1 ? " is" : "s are"} no longer accepted, so ${res.skipped_not_accepted === 1 ? "it was" : "they were"} skipped.`);
  if (res.skipped_not_found > 0) notes.push(`${res.skipped_not_found} gap${res.skipped_not_found === 1 ? " was" : "s were"} not found in this workspace.`);
  return { headline, notes };
}
