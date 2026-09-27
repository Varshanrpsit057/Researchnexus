import { describe, expect, it } from "vitest";
import type { ResearchGap } from "@/lib/api/types";
import { confidenceReasons, countByState, evidenceByPaper, filterGaps, gapMatches, NO_FILTERS, ruleCopy, runFailure, runOutcome, runProgress } from "./gaps";

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
  it("reads what happened to every candidate and paper from the job's progress", () => {
    const out = runOutcome({
      stage: "done",
      gaps: "done",
      count: "9",
      candidates: "118",
      dropped_insufficient_evidence: "0",
      dropped_self_support: "31",
      unchecked: "1",
      not_checked: "78",
      skipped_rejected: "1",
      kept_accepted: "2",
      rephrased: "9",
      profiled: "22",
      unprofiled: "4",
      profile_failed: "1",
    });
    expect(out).toEqual({
      kept: 9,
      candidates: 118,
      dropped: [
        { count: 31, reason: "weren't supported by their own evidence" },
        { count: 2, reason: "were accepted before, so kept as they were" },
        { count: 1, reason: "couldn't be checked this time (the model's reply was unusable or too slow), so it isn't shown" },
        { count: 1, reason: "was rejected before, so left out" },
      ],
      notChecked: 78,
      rephrased: 9,
      profiled: 22,
      unprofiled: 4,
      profileFailed: 1,
    });
  });

  it("still reads a run recorded before these counts existed, and copes with no progress", () => {
    expect(runOutcome({ gaps: "done", count: "2", dropped_unsupported: "1" })).toEqual({
      kept: 2,
      candidates: null,
      dropped: [{ count: 1, reason: "was phrased with something the evidence doesn't contain" }],
      notChecked: 0,
      rephrased: 0,
      profiled: 0,
      unprofiled: 0,
      profileFailed: 0,
    });
    expect(runOutcome({ gaps: "running" })).toBeNull();
    expect(runOutcome(undefined)).toBeNull();
  });
});

describe("runProgress", () => {
  it("names the step a run is on and how far through it", () => {
    expect(runProgress({ stage: "profiling", done: "5", total: "22" })).toEqual({
      stage: "profiling",
      label: "Reading the papers that have no research profile yet",
      done: 5,
      total: 22,
    });
    expect(runProgress({ stage: "checking", done: "0", total: "40" })).toMatchObject({ stage: "checking", done: 0, total: 40 });
    // a step with nothing to count shows no count
    expect(runProgress({ stage: "detecting", done: "0", total: "0" })).toMatchObject({ done: null, total: null });
    expect(runProgress({ stage: "checking", done: "0", total: "0" })).toMatchObject({ done: null, total: null });
  });

  it("reads a run that has only just started, or reports its stage the old way", () => {
    expect(runProgress(undefined)).toEqual({ stage: "starting", label: "Starting the run", done: null, total: null });
    expect(runProgress({ gaps: "running" }).stage).toBe("starting");
  });
});

describe("runFailure", () => {
  it("sends a rejected key to Settings, with the provider's reason", () => {
    const msg = "DeepSeek rejected the saved API key. Check it in Settings, or save a new one.";
    expect(runFailure(msg, { stage: "failed", error_code: "provider_error", error_kind: "auth" })).toEqual({
      message: msg,
      action: "settings",
      technical: null,
    });
  });

  it("offers another run for a busy provider or a run that ran too long", () => {
    expect(runFailure("DeepSeek is unavailable right now.", { error_code: "provider_error", error_kind: "unavailable" }).action).toBe("retry");
    expect(runFailure("The run took longer than 15 minutes and was stopped.", { error_code: "timeout" })).toEqual({
      message: "The run took longer than 15 minutes and was stopped.",
      action: "retry",
      technical: null,
    });
  });

  it("keeps an unexpected error's text as a technical detail, not the headline", () => {
    const out = runFailure("synthesis_internal_ref_77", { stage: "failed", error_code: "internal" });
    expect(out.message).toBe("The run failed before it finished. Papers read so far are kept; run it again to continue.");
    expect(out.technical).toBe("synthesis_internal_ref_77");
    expect(runFailure("", { gaps: "running" }).technical).toBeNull();
  });
});

describe("ruleCopy", () => {
  it("names how each rule finds its gap", () => {
    expect(ruleCopy("metric_divergence")).toBe("The papers report metrics, and no two of them share one.");
    expect(ruleCopy("some_new_rule")).toBe("Found by the some new rule rule.");
  });
});
