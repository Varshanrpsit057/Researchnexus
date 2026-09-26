import { describe, expect, it } from "vitest";
import type { ChatClaim, ChatSource } from "@/lib/api/types";
import { citationFromEvent, citationsIn, errorCopy, location, outcomeNotes, relativeTime, segmentAnswer, sourcesByPaper } from "./chat";

function source(paper: string, extra: Partial<ChatSource> = {}): ChatSource {
  return { chunk_id: `chk_${paper}`, paper_id: paper, paper_title: `Title ${paper}`, section: "Results", page: 3, quote: "q", truncated: false, ...extra };
}

function claim(i: number, sentence: string, sources: ChatSource[]): ChatClaim {
  return {
    claim_id: `clm_cm_${i}`,
    workspace_id: "ws",
    artefact_kind: "answer",
    artefact_id: "cm",
    sentence,
    supporting_chunk_ids: sources.map((s) => s.chunk_id),
    supporting_paper_ids: sources.map((s) => s.paper_id),
    is_supported: true,
    citation_precision: null,
    citation_recall: null,
    sources,
  };
}

describe("segmentAnswer", () => {
  it("places each citation right after the sentence it supports", () => {
    const content = "Dense retrieval improves recall. Reranking raises precision.";
    const segments = segmentAnswer(content, [
      claim(0, "Dense retrieval improves recall.", [source("a")]),
      claim(1, "Reranking raises precision.", [source("b"), source("a")]),
    ]);
    expect(segments.map((s) => (s.kind === "text" ? s.text : `[${s.citation.marker}]`))).toEqual([
      "Dense retrieval improves recall.",
      "[1]",
      " Reranking raises precision.",
      "[2]",
    ]);
    expect(citationsIn(segments).map((c) => c.sources.length)).toEqual([1, 2]);
  });

  it("keeps uncited text, and still lists a claim whose sentence it can't find", () => {
    const segments = segmentAnswer("One. Two.", [claim(0, "Two.", [source("a")]), claim(1, "Missing.", [source("b")])]);
    expect(segments.map((s) => (s.kind === "text" ? s.text : `[${s.citation.marker}]`))).toEqual(["One. Two.", "[1]", "[2]"]);
  });

  it("finds repeated sentences in order rather than twice at the first", () => {
    const segments = segmentAnswer("Same. Same.", [claim(0, "Same.", [source("a")]), claim(1, "Same.", [source("b")])]);
    expect(segments.map((s) => (s.kind === "text" ? s.text : `[${s.citation.marker}]`))).toEqual(["Same.", "[1]", " Same.", "[2]"]);
  });
});

describe("chat helpers", () => {
  it("reads a live citation event into the same shape, old or new backend", () => {
    const rich = citationFromEvent({ marker: "[2]", claim_id: "c", paper_id: "a", chunk_id: "k", quote: "q", section: null, page: null, sentence: "S.", sources: [source("a")] });
    expect(rich).toMatchObject({ marker: 2, sentence: "S.", sources: [{ paper_title: "Title a" }] });
    const old = citationFromEvent({ marker: "[1]", claim_id: "c", paper_id: "a", chunk_id: "k", quote: "q", section: "Intro", page: 1 });
    expect(old.sources).toEqual([{ chunk_id: "k", paper_id: "a", paper_title: null, section: "Intro", page: 1, quote: "q", truncated: false }]);
  });

  it("groups an answer's sources by paper, in citation order", () => {
    const rows = sourcesByPaper([
      { marker: 1, claimId: "1", sentence: "", sources: [source("b")] },
      { marker: 2, claimId: "2", sentence: "", sources: [source("a"), source("b")] },
    ]);
    expect(rows).toEqual([
      { paperId: "b", title: "Title b", markers: [1, 2] },
      { paperId: "a", title: "Title a", markers: [2] },
    ]);
  });

  it("says plainly what was left out or weakly supported", () => {
    expect(outcomeNotes({ answerable: true, hasText: true, unsupportedDropped: 2, warnings: ["faithfulness_below_threshold"] })).toEqual([
      "2 sentences were left out: no passage in this workspace supported them.",
      "This answer stays less close to its sources than the check expects. Read the quoted passages before relying on it.",
    ]);
    expect(outcomeNotes({ answerable: true, hasText: false, warnings: ["no_supported_sentences"] })[0]).toMatch(/none is shown/);
    expect(outcomeNotes({ answerable: false, hasText: false, warnings: ["not_answerable"] })).toEqual([]);
  });

  it("formats locations, errors and times", () => {
    expect(location({ section: "Results", page: 3 })).toBe("Results, page 3");
    expect(location({ section: null, page: null })).toBeNull();
    expect(errorCopy("llm_key_required", "x")).toMatch(/Settings/);
    expect(errorCopy("generation_failed", "The model failed.")).toBe("The model failed.");
    const now = Date.parse("2026-09-26T12:00:00Z");
    expect(relativeTime("2026-09-26T11:59:40Z", now)).toBe("just now");
    expect(relativeTime("2026-09-26T11:15:00Z", now)).toBe("45 min ago");
    expect(relativeTime("2026-09-26T07:00:00Z", now)).toBe("5 h ago");
    expect(relativeTime("2026-09-25T06:00:00Z", now)).toBe("yesterday");
    // a zone-less stamp is UTC, whatever the browser's timezone
    expect(relativeTime("2026-09-26T11:59:40", now)).toBe("just now");
    expect(relativeTime("2026-09-26T17:29:40+05:30", now)).toBe("just now");
  });
});
