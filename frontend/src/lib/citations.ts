import type { CitationFormat, CitationRelationship, CitationUse, CitationUseKind, LedgerPaper } from "@/lib/api/types";

export const USE_KINDS: CitationUseKind[] = ["answer", "comparison", "gap", "direction"];

export const USE_COPY: Record<CitationUseKind, { label: string; plural: string; where: string }> = {
  answer: { label: "Chat", plural: "Chat answers", where: "An answer in chat cites it" },
  comparison: { label: "Comparison", plural: "Comparison", where: "The comparison quotes it" },
  gap: { label: "Gaps", plural: "Gaps", where: "A gap rests on it" },
  direction: { label: "Directions", plural: "Directions", where: "A direction rests on it" },
};

export const RELATION_COPY: Record<Exclude<CitationRelationship, "none">, string> = {
  cited_by_seed: "The seed paper cites it",
  cites_seed: "It cites the seed paper",
  co_cited: "Cited alongside the seed paper",
};

/** Where the reference's metadata came from (app/services/citations/metadata_resolver.py). */
export const RESOLVED_COPY: Record<string, string> = {
  crossref: "Built from its DOI metadata",
  arxiv: "Built from its arXiv record",
  openalex: "Built from its title, authors and year",
  unresolved: "Not enough metadata to build a reference",
};

export const STYLE_LABEL: Record<CitationFormat, string> = { apa: "APA", ieee: "IEEE", bibtex: "BibTeX" };

export const NOT_AVAILABLE = "Not available";

export function totalUses(p: LedgerPaper): number {
  return USE_KINDS.reduce((n, k) => n + (p.counts[k] ?? 0), 0);
}

export function relationOf(p: LedgerPaper): string | null {
  return p.seed_relation && p.seed_relation !== "none" ? RELATION_COPY[p.seed_relation] : null;
}

export type CitedIn = "all" | "none" | CitationUseKind;
export type SortKey = "cited" | "newest" | "oldest" | "title" | "workspace";

export const SORT_LABEL: Record<SortKey, string> = {
  cited: "Most cited here",
  newest: "Newest first",
  oldest: "Oldest first",
  title: "Title",
  workspace: "Workspace order",
};

const fold = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");

/** Its metadata, and the words and passages of every place it is cited. */
export function paperMatches(p: LedgerPaper, query: string): boolean {
  const q = fold(query.trim());
  if (!q) return true;
  const hay = [
    p.title,
    ...p.authors,
    p.venue ?? "",
    p.year != null ? String(p.year) : "",
    p.doi ?? "",
    p.arxiv_id ?? "",
    ...p.uses.flatMap((u) => [u.text, u.quote ?? ""]),
  ]
    .map(fold)
    .join("\n");
  return q.split(/\s+/).every((t) => hay.includes(t));
}

export function filterPapers(papers: LedgerPaper[], citedIn: CitedIn, query: string): LedgerPaper[] {
  return papers.filter(
    (p) => (citedIn === "all" ? true : citedIn === "none" ? totalUses(p) === 0 : (p.counts[citedIn] ?? 0) > 0) && paperMatches(p, query),
  );
}

export function sortPapers(papers: LedgerPaper[], key: SortKey): LedgerPaper[] {
  const byOrder = new Map(papers.map((p, i) => [p.paper_id, i]));
  const order = (p: LedgerPaper) => byOrder.get(p.paper_id) ?? 0;
  const year = (p: LedgerPaper, missing: number) => p.year ?? missing;
  const sorted = [...papers];
  switch (key) {
    case "cited":
      return sorted.sort((a, b) => totalUses(b) - totalUses(a) || order(a) - order(b));
    case "newest":
      return sorted.sort((a, b) => year(b, -Infinity) - year(a, -Infinity) || order(a) - order(b));
    case "oldest":
      return sorted.sort((a, b) => year(a, Infinity) - year(b, Infinity) || order(a) - order(b));
    case "title":
      return sorted.sort((a, b) => a.title.localeCompare(b.title));
    default:
      return sorted;
  }
}

/** Where a use lives in the workspace: the chat thread, the comparison, the gap, the direction. */
export function useHref(workspaceId: string, use: CitationUse): string {
  const base = `/workspace/${workspaceId}`;
  switch (use.kind) {
    case "answer":
      return use.session_id ? `${base}/chat?session=${encodeURIComponent(use.session_id)}` : `${base}/chat`;
    case "comparison":
      return `${base}/compare`;
    case "gap":
      return `${base}/gaps?gap=${encodeURIComponent(use.artefact_id)}`;
    case "direction":
      return `${base}/directions?direction=${encodeURIComponent(use.artefact_id)}`;
  }
}

export function useLinkLabel(use: CitationUse): string {
  return { answer: "Open the chat", comparison: "Open the comparison", gap: "Open the gap", direction: "Open the direction" }[use.kind];
}

/** Every buildable reference in one style, in workspace order (IEEE numbers follow it). */
export function bibliography(papers: LedgerPaper[], style: CitationFormat): string {
  return papers
    .map((p) => p.reference.formatted[style])
    .filter((r): r is string => !!r && r !== NOT_AVAILABLE)
    .join(style === "bibtex" ? "\n\n" : "\n");
}

export function citable(p: LedgerPaper): boolean {
  return p.reference.resolved_from !== "unresolved";
}
