import type { Confidence, GapEvidence, GapType, GapUserState, ResearchGap } from "@/lib/api/types";

export const GAP_TYPE_LABEL: Record<GapType, string> = {
  METHOD_GAP: "Method gap",
  DATASET_GAP: "Dataset gap",
  EVALUATION_GAP: "Evaluation gap",
  DOMAIN_GAP: "Domain gap",
  PERFORMANCE_GAP: "Performance gap",
  GENERALIZATION_GAP: "Generalization gap",
  CONTRADICTION: "Contradiction",
  UNEXPLORED_COMBINATION: "Unexplored combination",
  TEMPORAL_GAP: "Temporal gap",
};

/** How each rule in app/services/gaps/candidates.py finds its gap, in plain words. */
const RULE_COPY: Record<string, string> = {
  method_coverage: "A method some papers use is missing from other papers that share their problem.",
  dataset_divergence: "The papers evaluate on datasets, and no two of them share one.",
  metric_divergence: "The papers report metrics, and no two of them share one.",
  shared_limitation: "Two or more papers state the same limitation, and none of them resolves it.",
  method_dataset_combination: "A method and a dataset, each used by several papers, never appear together.",
  temporal_staleness: "A topic several papers studied has not been revisited in years.",
  trail_contradiction: "Two papers connected in the research trail make claims that conflict.",
};

export function ruleCopy(rule: string): string {
  return RULE_COPY[rule] ?? (rule ? `Found by the ${rule.replace(/_/g, " ")} rule.` : "Found by a deterministic rule.");
}

export const STATE_LABEL: Record<GapUserState, string> = {
  candidate: "To review",
  accepted: "Accepted",
  rejected: "Rejected",
};

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

/** The bands of app/services/gaps/confidence.py::assign_confidence. */
export const CONFIDENCE_MEANING: Record<Confidence, string> = {
  high: "Three or more papers, mostly backed by full text, with agreeing evidence.",
  medium: "Two or more papers, at least a third of them backed by full text.",
  low: "Few papers, or evidence read only from abstracts.",
};

export type EvidenceRole = "supports_gap" | "shared_context" | "conflicts_with_gap";

export const ROLE_COPY: Record<EvidenceRole, { label: string; meaning: string }> = {
  supports_gap: { label: "States it", meaning: "The paper's own words that the gap rests on." },
  shared_context: { label: "Shares the setting", meaning: "Shows the paper works on the same problem, data or topic." },
  conflicts_with_gap: { label: "Conflicting claim", meaning: "A claim that disagrees with another paper's." },
};

export function roleOf(evidence: GapEvidence): EvidenceRole {
  return evidence.role in ROLE_COPY ? (evidence.role as EvidenceRole) : "supports_gap";
}

export interface PaperEvidence {
  paperId: string;
  supporting: GapEvidence[];
  conflicting: GapEvidence[];
}

/** Passages grouped by paper, in `papers` order, then any paper only a passage names. */
export function groupEvidence(papers: string[], supporting: GapEvidence[], conflicting: GapEvidence[] = []): PaperEvidence[] {
  const order = [...papers];
  for (const e of [...supporting, ...conflicting]) if (!order.includes(e.paper_id)) order.push(e.paper_id);
  return order
    .map((paperId) => ({
      paperId,
      supporting: supporting.filter((e) => e.paper_id === paperId),
      conflicting: conflicting.filter((e) => e.paper_id === paperId),
    }))
    .filter((g) => g.supporting.length + g.conflicting.length > 0);
}

/** Every passage a gap rests on, one group per paper, in the gap's own paper order. */
export function evidenceByPaper(gap: ResearchGap): PaperEvidence[] {
  return groupEvidence(gap.supporting_papers, gap.supporting_evidence, gap.conflicting_evidence);
}

export function passageCount(gap: ResearchGap): number {
  return gap.supporting_evidence.length + gap.conflicting_evidence.length;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Why a gap has its band, read from `confidence_basis` (never a made-up percentage). */
export function confidenceReasons(gap: ResearchGap): string[] {
  const basis = gap.confidence_basis;
  const out: string[] = [];
  const n = num(basis.n_supporting) ?? new Set(gap.supporting_papers).size;
  out.push(`${n} supporting paper${n === 1 ? "" : "s"}`);
  const coverage = num(basis.evidence_coverage) ?? gap.evidence_coverage;
  const fullText = Math.round(coverage * n);
  out.push(
    fullText === 0
      ? "Evidence read from abstracts only"
      : fullText === n
        ? "Every paper's evidence comes from its full text"
        : `${fullText} of ${n} papers backed by full text; the rest by abstracts`,
  );
  const selfSupport = typeof basis.self_support === "boolean" ? basis.self_support : gap.self_support_passed;
  out.push(selfSupport ? "Its statement is supported by its own evidence" : "Its statement was not confirmed by its own evidence");
  if (basis.limitation_agreement === true) out.push("The papers state the same limitation");
  if (basis.recency === "stale") out.push("The topic has not been revisited recently");
  return out;
}

export interface GapFilters {
  state: GapUserState | "all";
  type: GapType | "all";
  confidence: Confidence | "all";
  query: string;
}

export const NO_FILTERS: GapFilters = { state: "candidate", type: "all", confidence: "all", query: "" };

const fold = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");

/** Search the gap's own words, its terms, and the passages it quotes. */
export function gapMatches(gap: ResearchGap, query: string, paperTitles: Record<string, string> = {}): boolean {
  const q = fold(query.trim());
  if (!q) return true;
  const haystack = [
    gap.statement,
    gap.why_unaddressed,
    gap.proposed_direction,
    GAP_TYPE_LABEL[gap.gap_type] ?? gap.gap_type,
    ...gap.affected_methods,
    ...gap.affected_datasets,
    ...gap.supporting_evidence.map((e) => e.span.quote),
    ...gap.conflicting_evidence.map((e) => e.span.quote),
    ...gap.supporting_papers.map((p) => paperTitles[p] ?? ""),
  ]
    .map(fold)
    .join("\n");
  return q.split(/\s+/).every((term) => haystack.includes(term));
}

const CONFIDENCE_RANK: Record<Confidence, number> = { high: 0, medium: 1, low: 2 };

/** Strongest first: band, then how many papers back it, then the statement. */
export function sortGaps(gaps: ResearchGap[]): ResearchGap[] {
  return [...gaps].sort(
    (a, b) =>
      CONFIDENCE_RANK[a.confidence] - CONFIDENCE_RANK[b.confidence] ||
      new Set(b.supporting_papers).size - new Set(a.supporting_papers).size ||
      a.statement.localeCompare(b.statement),
  );
}

export function filterGaps(gaps: ResearchGap[], f: GapFilters, paperTitles: Record<string, string> = {}): ResearchGap[] {
  return sortGaps(
    gaps.filter(
      (g) =>
        (f.state === "all" || g.user_state === f.state) &&
        (f.type === "all" || g.gap_type === f.type) &&
        (f.confidence === "all" || g.confidence === f.confidence) &&
        gapMatches(g, f.query, paperTitles),
    ),
  );
}

export function countByState(gaps: ResearchGap[]): Record<GapUserState | "all", number> {
  const out = { candidate: 0, accepted: 0, rejected: 0, all: gaps.length };
  for (const g of gaps) out[g.user_state] += 1;
  return out;
}

export interface RunOutcome {
  kept: number;
  candidates: number | null;
  /** Why candidates did not become gaps, largest first, zeros left out. */
  dropped: { count: number; reason: string }[];
  profiled: number;
  unprofiled: number;
}

const DROP_REASONS: [key: string, reason: (n: number) => string][] = [
  ["dropped_insufficient_evidence", () => "lacked passages from two different papers"],
  ["dropped_unsupported", (n) => `${n === 1 ? "was" : "were"} phrased with something the evidence doesn't contain`],
  ["dropped_self_support", (n) => `${n === 1 ? "wasn't" : "weren't"} supported by ${n === 1 ? "its" : "their"} own evidence`],
  ["skipped_rejected", (n) => `${n === 1 ? "was" : "were"} rejected before, so left out`],
];

/** A finished gap job's progress (app/jobs/runner.py::run_gaps_job), as counts. */
export function runOutcome(progress: Record<string, string> | undefined): RunOutcome | null {
  if (!progress || progress.count == null) return null;
  const n = (k: string) => {
    const v = Number.parseInt(progress[k] ?? "", 10);
    return Number.isFinite(v) ? v : 0;
  };
  return {
    kept: n("count"),
    candidates: progress.candidates != null ? n("candidates") : null,
    dropped: DROP_REASONS.map(([key, reason]) => ({ count: n(key), reason: reason(n(key)) }))
      .filter((d) => d.count > 0)
      .sort((a, b) => b.count - a.count),
    profiled: n("profiled"),
    unprofiled: n("unprofiled"),
  };
}
