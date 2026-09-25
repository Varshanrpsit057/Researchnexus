import type { ChatClaim, ChatSource, RagStage, SseCitationEvent } from "@/lib/api/types";

/** One cited sentence of an answer and every passage that supports it. */
export interface Citation {
  marker: number;
  claimId: string;
  sentence: string;
  sources: ChatSource[];
}

export type Segment = { kind: "text"; text: string } | { kind: "cite"; citation: Citation };

/** A stored answer as prose with each citation placed right after the
 * sentence it supports -- the same shape a live stream builds, so an answer
 * reads identically before and after a reload. A claim whose sentence can't
 * be found in the text still gets its marker, at the end, so its evidence
 * stays inspectable. */
export function segmentAnswer(content: string, claims: ChatClaim[]): Segment[] {
  const segments: Segment[] = [];
  const unplaced: Citation[] = [];
  let cursor = 0;
  claims.forEach((claim, i) => {
    const citation: Citation = { marker: i + 1, claimId: claim.claim_id, sentence: claim.sentence, sources: claim.sources ?? [] };
    const at = claim.sentence ? content.indexOf(claim.sentence, cursor) : -1;
    if (at < 0) {
      unplaced.push(citation);
      return;
    }
    const end = at + claim.sentence.length;
    segments.push({ kind: "text", text: content.slice(cursor, end) });
    segments.push({ kind: "cite", citation });
    cursor = end;
  });
  if (cursor < content.length) segments.push({ kind: "text", text: content.slice(cursor) });
  for (const citation of unplaced) segments.push({ kind: "cite", citation });
  return segments.filter((s) => s.kind === "cite" || s.text !== "");
}

/** A live `citation` event in the same shape. Older backends sent one quote only. */
export function citationFromEvent(event: SseCitationEvent): Citation {
  const sources: ChatSource[] = event.sources?.length
    ? event.sources
    : [
        {
          chunk_id: event.chunk_id,
          paper_id: event.paper_id ?? "",
          paper_title: null,
          section: event.section,
          page: event.page,
          quote: event.quote,
          truncated: false,
        },
      ];
  return { marker: Number(event.marker.replace(/\D/g, "")) || 0, claimId: event.claim_id, sentence: event.sentence ?? "", sources };
}

export const citationsIn = (segments: Segment[]): Citation[] =>
  segments.flatMap((s) => (s.kind === "cite" ? [s.citation] : []));

/** The stages the stream reports, in the order a normal answer passes them. */
export const STAGES: RagStage[] = ["searching", "reading", "writing", "checking"];

export const STAGE_COPY: Record<RagStage, string> = {
  searching: "Searching this workspace's papers",
  reading: "Reading the most relevant passages",
  writing: "Writing an answer from them",
  checking: "Checking each sentence against its source",
  rewriting: "Rewriting to stay closer to the sources",
};

export interface PaperSources {
  paperId: string;
  title: string | null;
  markers: number[];
}

/** An answer's sources, one row per paper, in the order they are first cited. */
export function sourcesByPaper(citations: Citation[]): PaperSources[] {
  const byPaper = new Map<string, PaperSources>();
  for (const c of citations) {
    for (const s of c.sources) {
      const row = byPaper.get(s.paper_id) ?? { paperId: s.paper_id, title: s.paper_title, markers: [] };
      if (!row.markers.includes(c.marker)) row.markers.push(c.marker);
      row.title ??= s.paper_title;
      byPaper.set(s.paper_id, row);
    }
  }
  return [...byPaper.values()];
}

/** Where a passage sits in its paper: "Results, page 3". */
export function location(source: Pick<ChatSource, "section" | "page">): string | null {
  return [source.section, source.page != null ? `page ${source.page}` : null].filter(Boolean).join(", ") || null;
}

export interface Outcome {
  answerable: boolean;
  hasText: boolean;
  unsupportedDropped?: number;
  warnings?: string[];
}

/** What the reader should know about how an answer was checked, in plain words. */
export function outcomeNotes({ answerable, hasText, unsupportedDropped = 0, warnings = [] }: Outcome): string[] {
  if (!answerable) return [];
  const notes: string[] = [];
  if (!hasText && warnings.includes("no_supported_sentences")) {
    notes.push("No sentence of the answer could be matched to a source, so none is shown. Try regenerating or rephrasing.");
  }
  if (unsupportedDropped > 0) {
    notes.push(
      `${unsupportedDropped} sentence${unsupportedDropped === 1 ? " was" : "s were"} left out: no passage in this workspace supported ${unsupportedDropped === 1 ? "it" : "them"}.`,
    );
  }
  if (warnings.includes("faithfulness_below_threshold")) {
    notes.push("This answer stays less close to its sources than the check expects. Read the quoted passages before relying on it.");
  }
  return notes;
}

export function errorCopy(code: string | undefined, message: string | undefined): string {
  switch (code) {
    case "llm_key_required":
      return "No working LLM provider key is saved. Add one in Settings to ask questions.";
    case "network":
      return "The server couldn't be reached. Check the connection and try again.";
    default:
      return message || "Something went wrong while answering. Try again.";
  }
}

/** "just now", "5 min ago", "3 h ago", "yesterday", or a date. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  const minutes = Math.round((now - then) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  if (hours < 48) return "yesterday";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
