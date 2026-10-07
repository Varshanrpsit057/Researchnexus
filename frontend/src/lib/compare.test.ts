import { describe, expect, it } from "vitest";
import type { ComparisonCell, ComparisonResponse, ComparisonTable } from "@/lib/api/types";
import {
  cellStatus,
  coverageOf,
  emptyStatusesIn,
  fieldLabel,
  leftWorkspace,
  normalizeField,
  notYetCompared,
  pickColumns,
  tableCoverage,
} from "./compare";

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

const table: ComparisonTable = {
  comparison_id: "cmp_1",
  created_at: "2026-09-30T14:05:00+00:00",
  corner: "Field",
  papers: ["a", "b", "c"].map((id, i) => ({
    paper_id: id,
    title: `Paper ${id}`,
    authors: "",
    year: 2020 + i,
    kind: i === 0 ? "seed" : "member",
    read_from: "full_text",
    in_workspace: true,
    meta: `${2020 + i} · Full text`,
  })),
  rows: [
    {
      field: "method",
      label: "Method",
      cells: [
        { paper_id: "a", status: "found", text: "BM25", note: null },
        { paper_id: "b", status: "unsupported", text: "Unverified", note: null },
        { paper_id: "c", status: "not_stated", text: "Not stated", note: null },
      ],
    },
    {
      field: "dataset",
      label: "Datasets",
      cells: [
        { paper_id: "a", status: "no_text", text: "No text to read", note: null },
        { paper_id: "b", status: "found", text: "NQ", note: "The same passage also says: TriviaQA" },
        { paper_id: "c", status: "found", text: "MS MARCO", note: null },
      ],
    },
  ],
};

describe("the comparison table", () => {
  it("keeps the shown papers in the table's own order, whatever order they are asked in", () => {
    const picked = pickColumns(table, ["c", "a"]);
    expect(picked.papers.map((p) => p.paper_id)).toEqual(["a", "c"]);
    expect(picked.rows.map((r) => r.cells.map((c) => c.text))).toEqual([
      ["BM25", "Not stated"],
      ["No text to read", "MS MARCO"],
    ]);
    expect(pickColumns(table, []).papers).toEqual([]);
  });

  it("counts what was found, and lists only the empty states it has, in the legend's order", () => {
    expect(tableCoverage(table)).toEqual({ found: 3, total: 6 });
    expect(tableCoverage(pickColumns(table, ["a"]))).toEqual({ found: 1, total: 2 });
    expect(emptyStatusesIn(table)).toEqual(["not_stated", "unsupported", "no_text"]);
    expect(emptyStatusesIn(pickColumns(table, ["c"]))).toEqual(["not_stated"]);
  });
});
