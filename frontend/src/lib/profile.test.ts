import { describe, expect, it } from "vitest";
import type { ProfileField, ResearchProfile } from "@/lib/api/types";
import { approachGroups, briefOf, cleanQuote, contextGroups, groundingNote, hasUnmatched, metricRows } from "./profile";

const f = (value: string, extra: Partial<ProfileField> = {}): ProfileField => ({
  value,
  source_span: { paper_id: "p", section: null, page: 3, char_start: null, char_end: null, quote: `about ${value}` },
  status: "verified",
  ...extra,
});
const list = (...items: ProfileField[]) => ({ items });
const empty = { items: [] };

function profile(overrides: Partial<ResearchProfile> = {}): ResearchProfile {
  return {
    profile_id: "prof",
    paper_id: "p",
    workspace_id: null,
    grounding: "full_text",
    title: "T",
    abstract: "We propose X. It works well. More context follows here.",
    summary: "We propose X. It works well.",
    abstract_found: true,
    authors: [],
    year: null,
    venue: null,
    doi: null,
    arxiv_id: null,
    domain: f("Computer vision"),
    subdomains: empty,
    research_problem: f("Attendance is slow."),
    research_questions: empty,
    objectives: empty,
    keywords: [],
    methods: empty,
    models: empty,
    algorithms: empty,
    datasets: empty,
    evaluation_metrics: empty,
    findings: empty,
    limitations: empty,
    future_work: empty,
    important_entities: empty,
    cited_methods: empty,
    candidate_search_queries: [],
    extraction_confidence: "medium",
    extraction_model: "deepseek:deepseek-flash",
    tokens: { prompt: 0, completion: 0 },
    created_at: "2026-09-28T00:00:00Z",
    updated_at: "2026-09-28T00:00:00Z",
    ...overrides,
  };
}

describe("briefOf", () => {
  it("leads with the summary and keeps the full abstract behind it", () => {
    expect(briefOf(profile())).toEqual({
      summary: "We propose X. It works well.",
      fullAbstract: "We propose X. It works well. More context follows here.",
      abstractFound: true,
    });
  });

  it("shows a short abstract once, and a profile served before summaries existed its abstract", () => {
    expect(briefOf(profile({ abstract: "Short.", summary: "Short." })).fullAbstract).toBeNull();
    expect(briefOf(profile({ summary: undefined, abstract_found: undefined })).summary).toBe(
      "We propose X. It works well. More context follows here.",
    );
  });

  it("never presents stand-in body text as the abstract", () => {
    expect(briefOf(profile({ abstract: "C. ORGANIZATION OF THE PAPER This paper…", abstract_found: false }))).toEqual({
      summary: "",
      fullAbstract: null,
      abstractFound: false,
    });
  });
});

describe("metricRows", () => {
  it("shows a value only when the paper's evidence states it", () => {
    const rows = metricRows(
      profile({
        evaluation_metrics: list(
          f("Precision", { reported_value: { text: "96%", status: "verified" } }),
          f("Latency", { reported_value: { text: "120 ms", status: "unverified" } }),
          f("F1 score"),
        ),
      }),
    );
    expect(rows.map((r) => [r.text, r.value, r.state])).toEqual([
      ["Precision", "96%", "reported"],
      ["Latency", null, "unconfirmed"],
      ["F1 score", null, "not_reported"],
    ]);
  });
});

describe("sections", () => {
  it("lists only what the paper has, under plain headings", () => {
    const p = profile({ methods: list(f("Transfer learning")), datasets: list(f("Classroom images")), cited_methods: list(f("RFID")) });
    expect(approachGroups(p).map((g) => [g.label, g.items.map((i) => i.text)])).toEqual([
      ["Methods", ["Transfer learning"]],
      ["Datasets", ["Classroom images"]],
    ]);
    expect(contextGroups(p).map((g) => g.label)).toEqual(["Field", "Methods it cites"]);
  });

  it("says where the profile was read from, and whether anything wasn't matched to the text", () => {
    expect(groundingNote(profile({ grounding: "abstract" }))).toBe("Read from the abstract only");
    expect(hasUnmatched(profile())).toBe(false);
    expect(hasUnmatched(profile({ methods: list(f("Guessed", { status: "unverified", source_span: null })) }))).toBe(true);
  });
});

describe("cleanQuote", () => {
  it("joins a word broken across a PDF line", () => {
    expect(cleanQuote("the recog-\nnition rate of\n 95%")).toBe("the recognition rate of 95%");
    expect(cleanQuote("state-of-the-art")).toBe("state-of-the-art");
  });
});
