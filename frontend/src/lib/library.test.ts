import { describe, expect, it } from "vitest";
import type { LibraryPaper, Paper } from "@/lib/api/types";
import { filterLibrary, fromBrowser, mergeLibrary, nextStep, rolesLine, sortLibrary, viewCounts } from "./library";

function lib(overrides: Partial<LibraryPaper> = {}): LibraryPaper {
  return {
    id: "pap_1",
    title: "OnBoard: A Real-Time Bus Tracking Application",
    authors: ["M. Sulaiman", "S. Syamsul", "F. Yusoff"],
    year: 2025,
    venue: "ISCI",
    publisher: "IEEE",
    doi: "10.1109/isci.2025.1",
    source: "upload",
    has_abstract: true,
    has_full_text: true,
    coverage: { state: "full_text", source: "upload", status: null, reason: null, checked_at: null, has_abstract: true, retrievable: false },
    analyzed: true,
    roles: ["uploaded", "analyzed"],
    workspaces: [],
    last_run_id: null,
    last_active_at: "2026-10-06T10:00:00+00:00",
    ...overrides,
  };
}

const browserPaper = {
  id: "pap_old",
  title: "A Paper Uploaded Before",
  authors: [],
  year: 2019,
  venue: null,
  doi: null,
  arxiv_id: null,
  has_full_text: true,
  parse_confidence: "high",
  page_count: 8,
  sections: [],
  tables: [],
  warnings: [],
} as Paper;

describe("mergeLibrary", () => {
  it("keeps the server's papers and adds only the browser uploads it doesn't know, newest first", () => {
    const server = [lib(), lib({ id: "pap_2", title: "Second", last_active_at: "2026-10-01T00:00:00+00:00" })];
    const browser = [fromBrowser(browserPaper, "2026-10-03T00:00:00Z"), fromBrowser({ ...browserPaper, id: "pap_1" }, "2026-10-09T00:00:00Z")];
    const merged = mergeLibrary(server, browser);
    expect(merged.map((e) => e.id)).toEqual(["pap_1", "pap_old", "pap_2"]);
    expect(merged[0].onlyInThisBrowser).toBeUndefined(); // the server's record wins
    const old = merged[1];
    expect(old.analyzed).toBeNull(); // the browser can't say
    expect(old.coverage.state).toBe("full_text");
    expect(rolesLine(old)).toBe("Uploaded · in this browser");
  });
});

describe("filterLibrary and viewCounts", () => {
  const entries = mergeLibrary(
    [
      lib(),
      lib({ id: "pap_2", title: "Campus transit survey", authors: ["A. Radhika"], publisher: "Springer", roles: ["collected"], analyzed: false, workspaces: [{ workspace_id: "ws_1", title: "Bus" }] }),
      lib({ id: "pap_3", title: "Untouched", roles: ["searched"], analyzed: false }),
    ],
    [fromBrowser(browserPaper, "2026-01-01T00:00:00Z")],
  );

  it("narrows by view, and by every word of a query across title, authors, venue, publisher and DOI", () => {
    expect(filterLibrary(entries, "uploaded", "").map((e) => e.id)).toEqual(["pap_1", "pap_old"]);
    expect(filterLibrary(entries, "workspaces", "").map((e) => e.id)).toEqual(["pap_2"]);
    // a paper only this browser knows is never claimed to need analysis
    expect(filterLibrary(entries, "needs-analysis", "").map((e) => e.id)).toEqual(["pap_2", "pap_3"]);
    expect(filterLibrary(entries, "all", "radhika springer").map((e) => e.id)).toEqual(["pap_2"]);
    expect(filterLibrary(entries, "all", "10.1109").map((e) => e.id)).toEqual(["pap_2", "pap_1", "pap_3"]); // same time: by title
    expect(viewCounts(entries)).toEqual({ all: 4, uploaded: 2, workspaces: 1, "needs-analysis": 2 });
  });

  it("sorts by title or by publication year, unknown years last", () => {
    expect(sortLibrary(entries, "title").map((e) => e.title)[0]).toBe("A Paper Uploaded Before");
    const byYear = sortLibrary([lib({ id: "a", year: null }), lib({ id: "b", year: 2020 }), lib({ id: "c", year: 2024 })], "year");
    expect(byYear.map((e) => e.id)).toEqual(["c", "b", "a"]);
  });
});

describe("nextStep", () => {
  it("opens existing results, else discovers around an analysed paper, else asks for analysis", () => {
    expect(nextStep(lib({ last_run_id: "run_9" }))).toEqual({ label: "Open results", href: "/discover/pap_1?run=run_9" });
    expect(nextStep(lib())).toEqual({ label: "Discover related", href: "/discover/pap_1" });
    expect(nextStep(lib({ analyzed: false }))).toEqual({ label: "Analyse", href: "/papers/pap_1" });
    expect(nextStep(fromBrowser(browserPaper, "2026-01-01T00:00:00Z"))).toEqual({ label: "Open", href: "/papers/pap_old" });
  });
});
