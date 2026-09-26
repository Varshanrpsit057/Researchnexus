import { describe, expect, it } from "vitest";
import type { ResearchDirection, ResearchGap } from "@/lib/api/types";
import { countByState, critiqueAxes, directionMatches, directionReasons, filterDirections, generationOutcome, groupByGap, NO_FILTERS } from "./directions";

function direction(over: Partial<ResearchDirection> = {}): ResearchDirection {
  return {
    direction_id: "dir_1",
    workspace_id: "ws_1",
    gap_id: "gap_a",
    proposal: "Evaluate symbolic reasoning on the problem the papers share.",
    motivation: "The 2 papers addressing that shared problem do not adopt symbolic reasoning.",
    supporting_evidence: [{ paper_id: "p1", role: "shared_context", span: { paper_id: "p1", section: "Abstract", page: null, char_start: 0, char_end: 9, quote: "knowledge intensive tasks" } }],
    related_papers: ["p1", "p2"],
    suggested_method: "symbolic reasoning",
    possible_dataset: null,
    evaluation_strategy: "Compare against the papers' own reported results.",
    risks: ["The shared problem may be framed differently."],
    kind: "evidence_backed_inference",
    critique: { novelty: 2, specificity: 4, feasibility: 3, groundedness: 5 },
    confidence: "high",
    confidence_basis: { kind: "evidence_backed_inference", groundedness: 5, specificity: 4, novelty: 2, feasibility: 3, gap_confidence: "medium", gap_self_support: true, low_critique: true },
    flags: ["low_critique"],
    user_state: "candidate",
    generated_at: "2026-09-26T10:00:00Z",
    generator_model: "scripted",
    ...over,
  };
}

const gap = (gap_id: string, user_state: ResearchGap["user_state"] = "accepted") => ({ gap_id, user_state, statement: `statement ${gap_id}` }) as ResearchGap;

describe("critiqueAxes", () => {
  it("reads the four scores in reading order, feasibility capped", () => {
    expect(critiqueAxes(direction()).map((a) => [a.key, a.score, a.cap])).toEqual([
      ["groundedness", 5, 5],
      ["specificity", 4, 5],
      ["novelty", 2, 5],
      ["feasibility", 3, 3],
    ]);
    expect(critiqueAxes(direction({ critique: {} })).every((a) => a.score === null)).toBe(true);
  });
});

describe("directionReasons", () => {
  it("explains the band from its basis", () => {
    expect(directionReasons(direction())).toEqual([
      "Evidence-backed: its method and data come from the gap itself",
      "Grounded 5 of 5, specific 4 of 5 in the critique",
      "It rests on a medium-confidence gap",
      "The critique scored it 2 or lower on at least one axis",
    ]);
    expect(directionReasons(direction({ kind: "llm_hypothesis", confidence_basis: { gap_self_support: false }, critique: {}, flags: [] }))).toEqual([
      "A hypothesis: it proposes something the gap's evidence doesn't name",
      "Its gap's statement was not confirmed by its own evidence",
    ]);
  });
});

describe("filters and search", () => {
  it("searches the proposal, its plan, its gap and its passages", () => {
    expect(directionMatches(direction(), "symbolic results")).toBe(true);
    expect(directionMatches(direction(), "knowledge intensive")).toBe(true);
    expect(directionMatches(direction(), "multi-hop")).toBe(false);
    expect(directionMatches(direction(), "multi-hop", "a gap about multi-hop questions")).toBe(true);
  });

  it("filters by state and kind", () => {
    const ds = [direction(), direction({ direction_id: "dir_2", kind: "llm_hypothesis" }), direction({ direction_id: "dir_3", user_state: "accepted" })];
    expect(filterDirections(ds, NO_FILTERS).map((d) => d.direction_id)).toEqual(["dir_1", "dir_2"]);
    expect(filterDirections(ds, { ...NO_FILTERS, kind: "llm_hypothesis" }).map((d) => d.direction_id)).toEqual(["dir_2"]);
    expect(countByState(ds)).toEqual({ candidate: 2, accepted: 1, rejected: 0, all: 3 });
  });
});

describe("groupByGap", () => {
  it("puts directions under their gap, accepted gaps first, strongest direction first", () => {
    const ds = [
      direction({ direction_id: "low", gap_id: "gap_b", confidence: "low" }),
      direction({ direction_id: "hyp", gap_id: "gap_a", kind: "llm_hypothesis", confidence: "medium" }),
      direction({ direction_id: "ebi", gap_id: "gap_a", confidence: "medium" }),
      direction({ direction_id: "orphan", gap_id: "gap_gone" }),
    ];
    const groups = groupByGap(ds, [gap("gap_b", "candidate"), gap("gap_a")]);
    expect(groups.map((g) => [g.gapId, g.directions.map((d) => d.direction_id)])).toEqual([
      ["gap_a", ["ebi", "hyp"]],
      ["gap_b", ["low"]],
      ["gap_gone", ["orphan"]],
    ]);
    expect(groups[2].gap).toBeNull();
  });
});

describe("generationOutcome", () => {
  it("says what happened to every gap and proposal", () => {
    expect(generationOutcome({ directions: [], requested: 3, generated: 4, skipped_not_accepted: 1, skipped_not_found: 0, dropped_unsupported: 2 })).toEqual({
      headline: "Proposed 4 directions from 2 gaps.",
      notes: ["2 proposals were dropped for naming something the gap's evidence doesn't contain.", "1 gap is no longer accepted, so it was skipped."],
    });
    expect(generationOutcome({ directions: [], requested: 1, generated: 0, skipped_not_accepted: 0, skipped_not_found: 1, dropped_unsupported: 0 })).toEqual({
      headline: "No direction survived this run.",
      notes: ["1 gap was not found in this workspace."],
    });
  });
});
