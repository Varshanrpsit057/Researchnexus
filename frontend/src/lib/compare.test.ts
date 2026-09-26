import { describe, expect, it } from "vitest";
import type { ComparisonCell, ComparisonResponse } from "@/lib/api/types";
import { cellStatus, coverageOf, fieldLabel, leftWorkspace, normalizeField, notYetCompared } from "./compare";

const span = { paper_id: "a", section: "Method", page: 2, char_start: null, char_end: null, quote: "We use BM25." };

function cell(extra: Partial<ComparisonCell>): ComparisonCell {
  return { column: "method", text: null, span: null, claim_id: null, grounding: "full_text", conflicting: [], ...extra };
}

const comparison: ComparisonResponse = {
  comparison_id: "cmp_1",
  schema: ["method", "dataset"],
  generated_by: "deterministic_union",
  paper_ids: ["a", "b"],
  rows: [
    { paper_id: "a", cells: { method: cell({ text: "BM25", span, status: "found" }), dataset: cell({ status: "not_stated" }) } },
    { paper_id: "b", cells: { method: cell({ status: "unsupported" }), dataset: cell({ text: "NQ", span: { ...span, paper_id: "b" } }) } },
  ],
  coverage: 0.5,
  decontext_eval: null,
};

describe("compare helpers", () => {
  it("reads a cell's state, including cells stored before statuses existed", () => {
    expect(cellStatus(cell({ text: "BM25", span, status: "found" }))).toBe("found");
    expect(cellStatus(cell({ text: "BM25", span }))).toBe("found");
    expect(cellStatus(cell({ status: "unsupported" }))).toBe("unsupported");
    expect(cellStatus(cell({}))).toBe("unknown");
    expect(cellStatus(cell({ text: "value without evidence", status: "found" }))).toBe("unknown");
    expect(cellStatus(undefined)).toBe("unknown");
  });

  it("counts found cells over the papers shown", () => {
    expect(coverageOf(comparison, ["a", "b"])).toEqual({ found: 2, total: 4 });
    expect(coverageOf(comparison, ["a"])).toEqual({ found: 1, total: 2 });
  });

  it("knows which selected papers still need a run, and which left the workspace", () => {
    expect(notYetCompared(comparison, ["a", "c"])).toEqual(["c"]);
    expect(notYetCompared(null, ["a", "b"])).toEqual(["a", "b"]);
    expect(leftWorkspace(comparison, ["a"])).toEqual(["b"]);
  });

  it("names fields and normalises custom ones the way the backend does", () => {
    expect(fieldLabel("dataset")).toBe("Datasets");
    expect(fieldLabel("compute budget")).toBe("Compute budget");
    expect(normalizeField("  Compute   BUDGET ")).toBe("compute budget");
    expect(normalizeField("x".repeat(60))).toHaveLength(40);
  });
});
