/** Filtering and sorting a discovery run's results (remediation Phase 10).
 * Only narrows or reorders what the backend ranked; never changes a rank. */
import type { CitationRelationship, Confidence, DiscoveryStrategy, RelatedResult } from "@/lib/api/types";
import { STRATEGY_LABEL } from "@/lib/discovery";
import { DEFAULT_PUBLISHERS, isPreferred, publishersPhrase } from "@/lib/publishers";

export type FoundByFilter = "all" | "citation" | "recommendation" | "keyword" | "query_expansion";
/** "all", "preferred" (the reader's preferred publishers), or one publisher's name */
export type PublisherFilter = string;
export type ResultSort = "rank" | "newest" | "oldest";

export interface ResultFilters {
  query: string;
  band: Confidence | "all";
  foundBy: FoundByFilter;
  publisher?: PublisherFilter;
  /** the reader's preferred publishers; the default four when omitted */
  preferred?: readonly string[];
}

export const FOUND_BY_OPTIONS: { value: FoundByFilter; label: string }[] = [
  { value: "all", label: "Any search" },
  { value: "citation", label: "Citations" },
  { value: "recommendation", label: "Recommendations" },
  { value: "keyword", label: "Keyword search" },
  { value: "query_expansion", label: "Expanded queries" },
];

export const SORT_OPTIONS: { value: ResultSort; label: string }[] = [
  { value: "rank", label: "Rank" },
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
];

export function filterResults(results: RelatedResult[], f: ResultFilters): RelatedResult[] {
  const q = f.query.trim().toLowerCase();
  return results.filter((r) => {
    if (f.band !== "all" && r.band !== f.band) return false;
    if (f.foundBy !== "all" && !r.discovery_methods.includes(f.foundBy as DiscoveryStrategy)) return false;
    const publisher = f.publisher ?? "all";
    if (publisher === "preferred" && !isPreferred(r.paper.publisher, f.preferred ?? DEFAULT_PUBLISHERS)) return false;
    if (publisher !== "all" && publisher !== "preferred" && r.paper.publisher !== publisher) return false;
    if (!q) return true;
    const haystack = [r.paper.title, r.paper.venue ?? "", r.paper.publisher ?? "", ...r.paper.authors].join(" ").toLowerCase();
    return haystack.includes(q);
  });
}

const rankOf = (r: RelatedResult) => r.final_rank ?? Number.POSITIVE_INFINITY;

export function sortResults(results: RelatedResult[], sort: ResultSort): RelatedResult[] {
  const byRank = (a: RelatedResult, b: RelatedResult) => rankOf(a) - rankOf(b);
  const copy = [...results];
  if (sort === "rank") return copy.sort(byRank);
  const dir = sort === "newest" ? -1 : 1;
  return copy.sort((a, b) => {
    // a paper without a year goes last either way
    if (a.paper.year == null || b.paper.year == null) return (a.paper.year == null ? 1 : 0) - (b.paper.year == null ? 1 : 0) || byRank(a, b);
    return dir * (a.paper.year - b.paper.year) || byRank(a, b);
  });
}

/** The publisher filter's choices: any, the reader's preferred ones, then
 * each publisher these results name, most papers first. */
export function publisherOptions(
  results: RelatedResult[],
  preferred: readonly string[] = DEFAULT_PUBLISHERS,
): { value: PublisherFilter; label: string }[] {
  const counts = new Map<string, number>();
  for (const r of results) if (r.paper.publisher) counts.set(r.paper.publisher, (counts.get(r.paper.publisher) ?? 0) + 1);
  const named = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return [
    { value: "all", label: "Any publisher" },
    ...(preferred.length ? [{ value: "preferred", label: publishersPhrase(preferred) }] : []),
    ...named.map(([name, n]) => ({ value: name, label: `${name} (${n})` })),
  ];
}

export function authorLine(authors: string[]): string {
  if (authors.length === 0) return "Authors unknown";
  if (authors.length <= 2) return authors.join(", ");
  return `${authors.slice(0, 2).join(", ")} et al.`;
}

const RELATION: Record<CitationRelationship, string | null> = {
  cites_seed: "Cites the seed",
  cited_by_seed: "Cited by the seed",
  co_cited: "Cited alongside the seed",
  none: null,
};

/** How a paper was found: its citation link to the seed, then each search. */
export function foundBy(r: RelatedResult): string[] {
  const relation = RELATION[r.citation_relationship];
  const methods = r.discovery_methods
    .filter((m) => m !== "semantic_doc") // the same scoring pass as "semantic", named once
    .map((m) => STRATEGY_LABEL[m] ?? m.replace(/_/g, " "));
  return [...(relation ? [relation] : []), ...methods];
}
