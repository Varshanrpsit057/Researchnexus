import { describe, expect, it } from "vitest";
import type { PaperCoverage } from "@/lib/api/types";
import { COVERAGE_LABEL, coverageAction, coverageDetail, coverageShort } from "./coverage";

const c = (over: Partial<PaperCoverage>): PaperCoverage => ({
  state: "abstract_only",
  source: null,
  status: null,
  reason: null,
  checked_at: null,
  has_abstract: true,
  retrievable: true,
  ...over,
});

describe("coverage", () => {
  it("names the four states", () => {
    expect(Object.values(COVERAGE_LABEL)).toEqual(["Full text", "Abstract only", "Retrieval failed", "No text"]);
    expect(coverageShort("abstract_only")).toBe("abstract only");
  });

  it("says where full text came from", () => {
    expect(coverageDetail(c({ state: "full_text", source: "arxiv", status: "retrieved" }))).toBe("Read from its full text, from arXiv.");
    expect(coverageDetail(c({ state: "full_text", source: "upload", retrievable: false }))).toBe("Read from its full text, from the uploaded PDF.");
  });

  it("says why a paper has only its abstract, and what could change that", () => {
    expect(coverageDetail(c({}))).toBe("Only its abstract is available; its full text hasn't been looked for yet.");
    expect(coverageAction(c({}))).toBe("Get the full text");
    expect(coverageDetail(c({ status: "unavailable", reason: "elsewhere:jicet.org" }))).toBe(
      "Only its abstract is available. An open-access copy exists at jicet.org, which isn't one of the sources ResearchNexus downloads from.",
    );
    expect(coverageDetail(c({ status: "unavailable", reason: "no_open_access_copy" }))).toBe("Only its abstract is available: no open-access copy was found.");
    expect(coverageAction(c({ status: "unavailable" }))).toBe("Look again");
  });

  it("names a failure and says the abstract stands in", () => {
    const failed = c({ state: "retrieval_failed", status: "failed", reason: "http_403", source: "openalex" });
    expect(coverageDetail(failed)).toBe(
      "Its full text was found but couldn't be used: the source refused the download (HTTP 403). Its abstract is used meanwhile.",
    );
    expect(coverageAction(failed)).toBe("Try again");
    expect(coverageDetail(c({ state: "retrieval_failed", status: "failed", reason: "not_a_pdf", has_abstract: false }))).toBe(
      "Its full text was found but couldn't be used: the source sent a web page instead of the PDF (it may need a sign-in).",
    );
  });

  it("offers nothing when nothing can help", () => {
    expect(coverageAction(c({ state: "full_text" }))).toBeNull();
    expect(coverageAction(c({ state: "no_text", retrievable: false }))).toBeNull(); // an upload that couldn't be read
    expect(coverageDetail(c({ state: "no_text", status: "unavailable", reason: "no_identifier", has_abstract: false }))).toBe(
      "It has no abstract and no full text to read: it has no DOI or arXiv id to look its full text up by.",
    );
  });
});
