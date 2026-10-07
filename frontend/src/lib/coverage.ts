import type { CoverageState, PaperCoverage } from "@/lib/api/types";

/**
 * What text a paper is read from, in words (remediation Phase 7). The backend
 * decides the state and why; this only says it -- and never implies a paper
 * has more text than it does.
 */

export const COVERAGE_LABEL: Record<CoverageState, string> = {
  full_text: "Full text",
  abstract_only: "Abstract only",
  retrieval_failed: "Retrieval failed",
  no_text: "No text",
};

/** The lowercase form, for a run-on line ("Added from discovery · abstract only"). */
export const coverageShort = (state: CoverageState): string => COVERAGE_LABEL[state].toLowerCase();

const SOURCE: Record<string, string> = {
  arxiv: "arXiv",
  europepmc: "Europe PMC",
  openalex: "an open-access copy OpenAlex lists",
  semantic_scholar: "an open-access copy Semantic Scholar lists",
  unpaywall: "an open-access copy Unpaywall lists",
  core: "CORE's open-access repository copy",
  upload: "the uploaded PDF",
};

export function sourceLabel(source: string | null): string {
  return (source && SOURCE[source]) || "an open-access source";
}

const FAILURE: Record<string, string> = {
  not_a_pdf: "the source sent a web page instead of the PDF (it may need a sign-in)",
  too_large: "the PDF is larger than ResearchNexus reads",
  encrypted: "the PDF is password-protected",
  no_text_layer: "the PDF is a scan with no text to read",
  unreadable: "the file couldn't be read as a paper",
  timeout: "the source took too long to answer",
  unreachable: "the source couldn't be reached",
  rate_limited: "the source is limiting requests right now",
  lookup_failed: "the sources couldn't be asked right now",
  not_a_source: "the link led to a site ResearchNexus doesn't download from",
  internal: "something went wrong while reading it",
};

function failure(reason: string | null): string {
  if (!reason) return "it couldn't be downloaded";
  if (reason.startsWith("http_")) return `the source refused the download (HTTP ${reason.slice(5)})`;
  return FAILURE[reason] ?? "it couldn't be downloaded";
}

/** One sentence on what the paper is read from, and why it isn't more. */
export function coverageDetail(c: PaperCoverage): string {
  switch (c.state) {
    case "full_text":
      return `Read from its full text, from ${sourceLabel(c.source)}.`;
    case "retrieval_failed":
      return `Its full text was found but couldn't be used: ${failure(c.reason)}.${c.has_abstract ? " Its abstract is used meanwhile." : ""}`;
    case "abstract_only":
    case "no_text": {
      const has = c.state === "abstract_only" ? "Only its abstract is available" : "It has no abstract and no full text to read";
      if (c.status === null) return c.retrievable ? `${has}; its full text hasn't been looked for yet.` : `${has}.`;
      const reason = c.reason ?? "";
      if (reason.startsWith("elsewhere:")) {
        return `${has}. An open-access copy exists at ${reason.slice(10)}, which isn't one of the sources ResearchNexus downloads from.`;
      }
      if (reason === "no_identifier") return `${has}: it has no DOI or arXiv id to look its full text up by.`;
      return `${has}: no open-access copy was found.`;
    }
  }
}

/** The action that could get it more text, if any. */
export function coverageAction(c: PaperCoverage): string | null {
  if (!c.retrievable || c.state === "full_text") return null;
  if (c.state === "retrieval_failed") return "Try again";
  return c.status === null ? "Get the full text" : "Look again";
}
