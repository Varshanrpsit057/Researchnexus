import { describe, expect, it } from "vitest";
import type { RelatedResult } from "@/lib/api/types";
import { authorLine, filterResults, foundBy, publisherOptions, sortResults } from "./discovery-results";

const r = (over: Partial<RelatedResult> & { title: string; year?: number | null; authors?: string[] }): RelatedResult => ({
  paper: { id: over.title, title: over.title, authors: over.authors ?? ["A. Author"], year: "year" in over ? (over.year ?? null) : 2020, venue: "Venue", doi: null, url: null },
  discovery_methods: over.discovery_methods ?? ["keyword"],
  citation_relationship: over.citation_relationship ?? "none",
  signals: null,
  weights_version: "w0-initial",
  fused_score: over.fused_score ?? 0.5,
  rerank_score: null,
  final_rank: "final_rank" in over ? (over.final_rank ?? null) : 1,
  band: over.band ?? "medium",
  explanation: null,
});

const results = [
  r({ title: "Dense Passage Retrieval", final_rank: 1, band: "high", year: 2020, discovery_methods: ["citation", "semantic"], citation_relationship: "cites_seed" }),
  r({ title: "Sparse Retrieval Revisited", final_rank: 2, band: "medium", year: 2023, authors: ["B. Smith", "C. Jones", "D. Lee"] }),
  r({ title: "A Survey of Databases", final_rank: 3, band: "low", year: 2011, discovery_methods: ["recommendation"] }),
];

describe("discovery results", () => {
  it("filters by text in the title, authors or venue, by band and by how it was found", () => {
    expect(filterResults(results, { query: "retrieval", band: "all", foundBy: "all" }).map((x) => x.paper.title)).toEqual([
      "Dense Passage Retrieval",
      "Sparse Retrieval Revisited",
    ]);
    expect(filterResults(results, { query: "jones", band: "all", foundBy: "all" })).toHaveLength(1);
    expect(filterResults(results, { query: "", band: "high", foundBy: "all" })).toHaveLength(1);
    expect(filterResults(results, { query: "", band: "all", foundBy: "citation" }).map((x) => x.paper.title)).toEqual(["Dense Passage Retrieval"]);
    expect(filterResults(results, { query: "", band: "all", foundBy: "recommendation" })).toHaveLength(1);
  });

  it("sorts by rank, newest or oldest, keeping rank order among equals", () => {
    expect(sortResults(results, "rank").map((x) => x.final_rank)).toEqual([1, 2, 3]);
    expect(sortResults(results, "newest").map((x) => x.paper.year)).toEqual([2023, 2020, 2011]);
    expect(sortResults(results, "oldest").map((x) => x.paper.year)).toEqual([2011, 2020, 2023]);
    const unranked = r({ title: "Not ranked yet", final_rank: null, year: null });
    expect(sortResults([unranked, ...results], "rank").at(-1)?.paper.title).toBe("Not ranked yet");
    expect(sortResults([unranked, ...results], "newest").at(-1)?.paper.title).toBe("Not ranked yet");
  });

  it("names authors compactly and says how a paper was found", () => {
    expect(authorLine(["B. Smith", "C. Jones", "D. Lee"])).toBe("B. Smith, C. Jones et al.");
    expect(authorLine(["B. Smith"])).toBe("B. Smith");
    expect(authorLine([])).toBe("Authors unknown");
    expect(foundBy(results[0])).toEqual(["Cites the seed", "Citations", "Passage similarity"]);
  });
});

describe("publishers", () => {
  const withPublisher = (title: string, publisher: string | null, rank: number): RelatedResult => {
    const base = r({ title, final_rank: rank });
    return { ...base, paper: { ...base.paper, publisher } };
  };
  const mixed = [
    withPublisher("From IEEE", "IEEE", 1),
    withPublisher("From MDPI", "MDPI", 2),
    withPublisher("From Springer", "Springer", 3),
    withPublisher("Unknown publisher", null, 4),
    withPublisher("Also IEEE", "IEEE", 5),
  ];

  it("filters to the preferred four, or to one publisher", () => {
    const all = { query: "", band: "all" as const, foundBy: "all" as const };
    expect(filterResults(mixed, { ...all, publisher: "preferred" }).map((x) => x.paper.title)).toEqual(["From IEEE", "From Springer", "Also IEEE"]);
    expect(filterResults(mixed, { ...all, publisher: "MDPI" }).map((x) => x.paper.title)).toEqual(["From MDPI"]);
    expect(filterResults(mixed, { ...all, publisher: "all" })).toHaveLength(5);
    expect(filterResults(mixed, { ...all, query: "springer" }).map((x) => x.paper.title)).toEqual(["From Springer"]);
  });

  it("offers each publisher the results name, most papers first", () => {
    expect(publisherOptions(mixed).map((o) => o.value)).toEqual(["all", "preferred", "IEEE", "MDPI", "Springer"]);
    expect(publisherOptions(mixed)[2].label).toBe("IEEE (2)");
  });
});

describe("the reader's own preferred publishers", () => {
  it("filter and name the preferred choice by the reader's list", () => {
    const pub = (title: string, publisher: string) => {
      const base = r({ title });
      return { ...base, paper: { ...base.paper, publisher } };
    };
    const rows = [pub("From MDPI", "MDPI"), pub("From IEEE", "IEEE")];
    const all = { query: "", band: "all" as const, foundBy: "all" as const };
    expect(filterResults(rows, { ...all, publisher: "preferred", preferred: ["MDPI"] }).map((x) => x.paper.title)).toEqual(["From MDPI"]);
    expect(publisherOptions(rows, ["MDPI", "Wiley"])[1]).toEqual({ value: "preferred", label: "MDPI or Wiley" });
    // nothing preferred: no "preferred" choice at all
    expect(publisherOptions(rows, []).map((o) => o.value)).toEqual(["all", "IEEE", "MDPI"]);
  });
});
