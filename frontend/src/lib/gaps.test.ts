import { describe, expect, it } from "vitest";
import type { ResearchGap } from "@/lib/api/types";
import { confidenceReasons, countByState, evidenceByPaper, filterGaps, gapMatches, NO_FILTERS, ruleCopy, runOutcome } from "./gaps";

function gap(over: Partial<ResearchGap> = {}): ResearchGap {
  const span = (paper_id: string, quote: string, section: string | null = "Abstract") => ({
    paper_id,
    section,
    page: null,
    char_start: 0,
    char_end: quote.length,
    quote,
  });
  return {
    gap_id: "gap_1",
    workspace_id: "ws_1",
    statement: "No workspace paper applies BM25 to the research problem shared by 2 of the papers.",
    gap_type: "METHOD_GAP",
    supporting_papers: ["p2", "p3"],
    supporting_evidence: [
      { paper_id: "p2", role: "shared_context", span: span("p2", "hallucination in knowledge intensive tasks") },
      { paper_id: "p3", role: "shared_context", span: span("p3", "reduces hallucination") },
    ],
    conflicting_evidence: [],
    why_unaddressed: "The 2 papers addressing that shared problem do not adopt BM25.",
    affected_methods: ["BM25"],
    affected_datasets: [],
    evidence_coverage: 0,
    novelty_assessment: "under-addressed in this workspace",
    confidence: "low",
    confidence_basis: { n_supporting: 2, evidence_coverage: 0, self_support: true, limitation_agreement: false, recency: "unknown", detection_rule: "method_coverage" },
    proposed_direction: "Evaluate BM25 on the shared problem setting.",
    detection_rule: "method_coverage",
    self_support_passed: true,
    user_state: "candidate",
    generated_at: "2026-09-26T10:00:00Z",
    generator_model: null,
    ...over,
  };
}

describe("evidenceByPaper", () => {
  it("groups every passage under its paper, supporting papers first, conflicting-only papers after", () => {
    const g = gap({
      gap_type: "CONTRADICTION",
      conflicting_evidence: [
        { paper_id: "p3", role: "conflicts_with_gap", span: { paper_id: "p3", section: null, page: 2, char_start: null, char_end: null, quote: "x" } },
        { paper_id: "p9", role: "conflicts_with_gap", span: { paper_id: "p9", section: null, page: null, char_start: null, char_end: null, quote: "y" } },
      ],
    });
    const groups = evidenceByPaper(g);
    expect(groups.map((p) => p.paperId)).toEqual(["p2", "p3", "p9"]);
    expect(groups[1]).toMatchObject({ supporting: [{ span: { quote: "reduces hallucination" } }], conflicting: [{ span: { quote: "x" } }] });
  });
});

describe("confidenceReasons", () => {
  it("reads the band's basis in plain words", () => {
    expect(confidenceReasons(gap())).toEqual([
      "2 supporting papers",
      "Evidence read from abstracts only",
      "Its statement is supported by its own evidence",
    ]);
    const strong = gap({ confidence_basis: { n_supporting: 3, evidence_coverage: 0.667, self_support: true, limitation_agreement: true } });
    expect(confidenceReasons(strong)).toEqual([
      "3 supporting papers",
      "2 of 3 papers backed by full text; the rest by abstracts",
      "Its statement is supported by its own evidence",
      "The papers state the same limitation",
    ]);
  });

  it("falls back to the gap's own fields when the basis lacks them", () => {
    expect(confidenceReasons(gap({ confidence_basis: {}, evidence_coverage: 1, self_support_passed: false }))).toEqual([
      "2 supporting papers",
      "Every paper's evidence comes from its full text",
      "Its statement was not confirmed by its own evidence",
    ]);
  });
});

describe("gapMatches / filterGaps", () => {
  it("searches the statement, terms, quoted passages and paper titles, every word", () => {
    expect(gapMatches(gap(), "bm25 shared")).toBe(true);
    expect(gapMatches(gap(), "knowledge intensive")).toBe(true); // a quoted passage
    expect(gapMatches(gap(), "symbolic")).toBe(false);
    expect(gapMatches(gap(), "symbolic", { p2: "A Competing Symbolic Approach" })).toBe(true);
    expect(gapMatches(gap(), "  ")).toBe(true);
  });

  it("filters by state, type and band, strongest first", () => {
    const gaps = [
      gap({ gap_id: "a", confidence: "low" }),
      gap({ gap_id: "b", confidence: "medium", gap_type: "EVALUATION_GAP" }),
      gap({ gap_id: "c", user_state: "accepted" }),
    ];
    expect(filterGaps(gaps, NO_FILTERS).map((g) => g.gap_id)).toEqual(["b", "a"]);
    expect(filterGaps(gaps, { ...NO_FILTERS, type: "METHOD_GAP" }).map((g) => g.gap_id)).toEqual(["a"]);
    expect(filterGaps(gaps, { ...NO_FILTERS, state: "all", confidence: "low" }).map((g) => g.gap_id)).toEqual(["a", "c"]);
    expect(countByState(gaps)).toEqual({ candidate: 2, accepted: 1, rejected: 0, all: 3 });
  });
});

describe("runOutcome", () => {
  it("reads what happened to every candidate from the job's progress", () => {
    const out = runOutcome({
      gaps: "done",
      count: "4",
      candidates: "6",
      dropped_insufficient_evidence: "0",
      dropped_unsupported: "0",
      dropped_self_support: "1",
      skipped_rejected: "1",
      profiled: "3",
      unprofiled: "1",
    });
    expect(out).toEqual({
      kept: 4,
      candidates: 6,
      dropped: [
        { count: 1, reason: "wasn't supported by its own evidence" },
        { count: 1, reason: "was rejected before, so left out" },
      ],
      profiled: 3,
      unprofiled: 1,
    });
  });

  it("copes with a job that only reports a count, and with no progress", () => {
    expect(runOutcome({ gaps: "done", count: "2" })).toEqual({ kept: 2, candidates: null, dropped: [], profiled: 0, unprofiled: 0 });
    expect(runOutcome({ gaps: "running" })).toBeNull();
    expect(runOutcome(undefined)).toBeNull();
  });
});

describe("ruleCopy", () => {
  it("names how each rule finds its gap", () => {
    expect(ruleCopy("metric_divergence")).toBe("The papers report metrics, and no two of them share one.");
    expect(ruleCopy("some_new_rule")).toBe("Found by the some new rule rule.");
  });
});
