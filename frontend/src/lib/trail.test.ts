import { describe, expect, it } from "vitest";
import type { GroupedTrail, RelationshipType, TrailEdge, TrailGroupEntry } from "@/lib/api/types";
import {
  confidenceReasons,
  conclusion,
  countByState,
  describeEvidence,
  filterTrail,
  flattenTrail,
  ruleReasons,
  type TrailEntry,
} from "./trail";

function edge(overrides: Partial<TrailEdge> = {}): TrailEdge {
  return {
    edge_id: "edge_1",
    run_id: "run_1",
    workspace_id: "ws_1",
    source_paper_id: "pap_seed",
    target_paper_id: "pap_t",
    relationship_type: "SIMILAR",
    detection_method: "rule",
    rule_fired: "semantic_doc>=0.65 OR problem_sim>=0.60",
    llm_confirmed: false,
    evidence: [{ role: "target_claim", span: { paper_id: "pap_t", section: "Abstract", page: null, char_start: 0, char_end: 10, quote: "Agents plan with tools." } }],
    supporting_references: ["pap_t"],
    confidence: "medium",
    confidence_basis: { signal_agreement: 6, evidence_complete: true, rule_confidence: "medium", llm_certainty: "none", llm_disagreed: false },
    user_state: "pending",
    created_at: "2026-09-25T00:00:00Z",
    ...overrides,
  };
}

function entry(type: RelationshipType, e: Partial<TrailEdge> = {}, extra: Partial<TrailGroupEntry> = {}): TrailEntry {
  return {
    type,
    target: { id: "pap_t", title: "Agentic Planning", year: 2025, authors: ["A. Author"], venue: "NeurIPS" },
    edge: edge({ relationship_type: type, ...e }),
    ranking: { final_rank: 2, band: "high", signals: { semantic_doc: 0.81, method_sim: 0.62, problem_sim: 0.7 } },
    ...extra,
  };
}

describe("flattenTrail", () => {
  it("orders by relationship type, then confidence, keeping each entry's type", () => {
    const groups = Object.fromEntries(
      ["FOUNDATIONAL", "SIMILAR", "RECENT", "COMPETING", "METHOD_EXTENSION", "DATASET_RELATED", "POTENTIALLY_CONTRADICTORY"].map((t) => [t, []]),
    ) as unknown as GroupedTrail["groups"];
    groups.SIMILAR = [
      { target: { id: "a", title: "Low", year: 2020 }, edge: edge({ edge_id: "e_low", confidence: "low" }) },
      { target: { id: "b", title: "High", year: 2020 }, edge: edge({ edge_id: "e_high", confidence: "high" }) },
    ];
    groups.FOUNDATIONAL = [{ target: { id: "c", title: "Old", year: 2001 }, edge: edge({ edge_id: "e_f", relationship_type: "FOUNDATIONAL" }) }];
    const flat = flattenTrail({ seed_paper_id: "pap_seed", groups });
    expect(flat.map((e) => e.edge.edge_id)).toEqual(["e_f", "e_high", "e_low"]);
    expect(flat[0].type).toBe("FOUNDATIONAL");
  });
});

describe("ruleReasons", () => {
  it("explains a method extension with the measured value and the rule's threshold", () => {
    const reasons = ruleReasons(entry("METHOD_EXTENSION", { rule_fired: "cites_seed AND method_sim>=0.55" }));
    expect(reasons).toEqual(["It cites the seed paper.", "Its method is 62% similar to the seed's (the rule needs 55%)."]);
  });

  it("explains a foundational link with both publication years", () => {
    const reasons = ruleReasons(
      entry("FOUNDATIONAL", { rule_fired: "cited_by_seed AND target_year < seed_year" }, { target: { id: "p", title: "Old", year: 2016 } }),
      2020,
    );
    expect(reasons).toEqual(["The seed paper cites it.", "It came first: 2016, before the seed's 2020."]);
  });

  it("leaves numbers out when the run has no measured value, rather than inventing one", () => {
    const reasons = ruleReasons(entry("SIMILAR", {}, { ranking: null }));
    expect(reasons).toEqual(["Its overall topic closely matches the seed's."]);
  });

  it("falls back to the rule itself for a rule it does not recognise", () => {
    expect(ruleReasons(entry("SIMILAR", { rule_fired: "some_new_rule" }))).toEqual(["Rule: some_new_rule"]);
  });
});

describe("confidenceReasons", () => {
  it("states why a rule-only edge stops at medium", () => {
    expect(confidenceReasons(entry("SIMILAR").edge)).toEqual([
      "6 ranking signals agree.",
      "The evidence is complete.",
      "Not checked by a language model, and high confidence needs that confirmation.",
    ]);
  });

  it("reports a language model's disagreement", () => {
    const e = entry("SIMILAR", { confidence: "low", confidence_basis: { signal_agreement: 1, evidence_complete: true, llm_disagreed: true, llm_certainty: "low" } }).edge;
    expect(confidenceReasons(e)).toContain("A language model reviewed it and did not confirm it.");
  });
});

describe("describeEvidence", () => {
  it("attributes each span to its paper and says when only a title is on record", () => {
    expect(describeEvidence({ role: "seed_reference", span: { paper_id: "pap_seed", section: "References", page: null, char_start: null, char_end: null, quote: "[4] x" } })).toMatchObject({
      side: "seed",
      label: "The seed paper's reference list",
      titleOnly: false,
    });
    expect(describeEvidence({ role: "similarity_signal", span: { paper_id: "pap_t", section: null, page: null, char_start: null, char_end: null, quote: "Title" } })).toMatchObject({
      side: "target",
      titleOnly: true,
    });
  });
});

describe("filterTrail and countByState", () => {
  const entries = [
    entry("SIMILAR", { edge_id: "e1", user_state: "pending", confidence: "high" }),
    entry("FOUNDATIONAL", { edge_id: "e2", user_state: "accepted" }, { target: { id: "p2", title: "Dense Passage Retrieval", year: 2016 } }),
    entry("SIMILAR", { edge_id: "e3", user_state: "rejected" }),
  ];

  it("counts every state", () => {
    expect(countByState(entries)).toEqual({ pending: 1, accepted: 1, rejected: 1 });
  });

  it("filters by state, type, confidence and a search over titles, authors and quotes", () => {
    expect(filterTrail(entries, { state: "pending" }).map((e) => e.edge.edge_id)).toEqual(["e1"]);
    expect(filterTrail(entries, { state: "accepted", types: new Set(["FOUNDATIONAL"]) }).map((e) => e.edge.edge_id)).toEqual(["e2"]);
    expect(filterTrail(entries, { state: "pending", band: "low" })).toEqual([]);
    expect(filterTrail(entries, { state: "accepted", query: "passage retrieval" }).map((e) => e.edge.edge_id)).toEqual(["e2"]);
    expect(filterTrail(entries, { state: "pending", query: "plan TOOLS" }).map((e) => e.edge.edge_id)).toEqual(["e1"]); // quote text
    expect(filterTrail(entries, { state: "pending", query: "a. author" }).map((e) => e.edge.edge_id)).toEqual(["e1"]);
  });
});

describe("conclusion", () => {
  it("states the relationship as a finding about the target", () => {
    expect(conclusion("METHOD_EXTENSION")).toBe("It builds on the seed paper's method.");
    expect(conclusion("POTENTIALLY_CONTRADICTORY")).toBe("Its findings may contradict the seed paper's.");
  });
});
