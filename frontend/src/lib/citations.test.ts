import { describe, expect, it } from "vitest";
import type { LedgerPaper } from "@/lib/api/types";
import { bibliography, filterPapers, paperMatches, relationOf, sortPapers, totalUses, useHref } from "./citations";

function paper(over: Partial<LedgerPaper> = {}): LedgerPaper {
  return {
    paper_id: "p1",
    title: "Retrieval-Augmented Generation",
    authors: ["Patrick Lewis"],
    year: 2020,
    venue: "NeurIPS",
    doi: "10.5555/rag",
    arxiv_id: null,
    url: null,
    role: "seed",
    grounding: "full_text",
    reference: { resolved_from: "crossref", formatted: { apa: "Lewis, P. (2020). RAG.", ieee: "[1] P. Lewis, RAG, 2020.", bibtex: "@article{lewis2020,}" } },
    reference_count: 30,
    seed_relation: null,
    connections: [],
    uses: [],
    counts: { answer: 0, comparison: 0, gap: 0, direction: 0 },
    ...over,
  };
}

const cited = paper({
  paper_id: "p2",
  title: "REALM",
  authors: ["Kelvin Guu"],
  year: 2018,
  role: "member",
  seed_relation: "cited_by_seed",
  reference: { resolved_from: "unresolved", formatted: { apa: "Not available", ieee: "Not available", bibtex: "Not available" } },
  uses: [
    { kind: "answer", artefact_id: "msg_1", text: "REALM retrieves while it pre-trains.", quote: "a latent knowledge retriever", section: "Abstract", page: null, created_at: null, session_id: "cs_1" },
    { kind: "gap", artefact_id: "gap_1", text: "No paper pairs retrieval with pre-training.", quote: "q", section: null, page: null, created_at: null, state: "accepted" },
  ],
  counts: { answer: 1, comparison: 0, gap: 1, direction: 0 },
});

describe("ledger papers", () => {
  it("counts every use and names its relation to the seed", () => {
    expect(totalUses(cited)).toBe(2);
    expect(relationOf(cited)).toBe("The seed paper cites it");
    expect(relationOf(paper())).toBeNull();
  });

  it("searches metadata and the words and passages of every use", () => {
    expect(paperMatches(cited, "guu")).toBe(true);
    expect(paperMatches(cited, "latent retriever")).toBe(true);
    expect(paperMatches(cited, "pre-training retrieval")).toBe(true); // a gap's statement
    expect(paperMatches(cited, "transformer")).toBe(false);
  });

  it("filters by where it is cited", () => {
    const all = [paper(), cited];
    expect(filterPapers(all, "gap", "").map((p) => p.paper_id)).toEqual(["p2"]);
    expect(filterPapers(all, "none", "").map((p) => p.paper_id)).toEqual(["p1"]);
    expect(filterPapers(all, "comparison", "").map((p) => p.paper_id)).toEqual([]);
  });

  it("sorts by use, year or title, ties in workspace order", () => {
    const all = [paper(), cited, paper({ paper_id: "p3", title: "Atlas", year: null })];
    expect(sortPapers(all, "cited").map((p) => p.paper_id)).toEqual(["p2", "p1", "p3"]);
    expect(sortPapers(all, "newest").map((p) => p.paper_id)).toEqual(["p1", "p2", "p3"]);
    expect(sortPapers(all, "oldest").map((p) => p.paper_id)).toEqual(["p2", "p1", "p3"]);
    expect(sortPapers(all, "title").map((p) => p.paper_id)).toEqual(["p3", "p2", "p1"]);
  });
});

describe("links and export", () => {
  it("links every use to where it lives", () => {
    expect(useHref("ws_1", cited.uses[0])).toBe("/workspace/ws_1/chat?session=cs_1");
    expect(useHref("ws_1", cited.uses[1])).toBe("/workspace/ws_1/gaps?gap=gap_1");
    expect(useHref("ws_1", { ...cited.uses[1], kind: "direction", artefact_id: "dir_1" })).toBe("/workspace/ws_1/directions?direction=dir_1");
  });

  it("exports only the references that could be built", () => {
    expect(bibliography([paper(), cited], "apa")).toBe("Lewis, P. (2020). RAG.");
    expect(bibliography([paper(), paper({ paper_id: "p3" })], "bibtex")).toBe("@article{lewis2020,}\n\n@article{lewis2020,}");
  });
});
