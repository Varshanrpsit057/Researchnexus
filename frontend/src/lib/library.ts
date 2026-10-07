import type { LibraryPaper, LibraryRole, Paper } from "@/lib/api/types";

/**
 * The reader's paper library (remediation, 2026-10-06): the server's list of
 * every paper they uploaded, analysed, searched from or collected, plus the
 * uploads this browser remembers from before uploads were credited to an
 * account. Pure helpers, so the page only draws.
 */

/** A library paper; one known only to this browser can't say whether it was analysed. */
export interface LibraryEntry extends Omit<LibraryPaper, "analyzed"> {
  analyzed: boolean | null;
  /** remembered by this browser, not (yet) by the server */
  onlyInThisBrowser?: boolean;
}

/** A paper this browser uploaded before uploads were credited to an account. */
export function fromBrowser(paper: Paper, addedAt: string): LibraryEntry {
  return {
    id: paper.id,
    title: paper.title,
    authors: paper.authors,
    year: paper.year,
    venue: paper.venue,
    publisher: paper.publisher ?? null,
    doi: paper.doi,
    source: paper.source ?? "upload",
    has_abstract: paper.has_abstract ?? false,
    has_full_text: paper.has_full_text,
    coverage: paper.coverage ?? {
      state: paper.has_full_text ? "full_text" : "no_text",
      source: null,
      status: null,
      reason: null,
      checked_at: null,
      has_abstract: paper.has_abstract ?? false,
      retrievable: false,
    },
    analyzed: null,
    roles: ["uploaded"],
    workspaces: [],
    last_run_id: null,
    last_active_at: addedAt,
    onlyInThisBrowser: true,
  };
}

/** The server's library, then this browser's uploads it doesn't know, newest first. */
export function mergeLibrary(server: LibraryPaper[], browser: LibraryEntry[]): LibraryEntry[] {
  const known = new Set(server.map((p) => p.id));
  const merged: LibraryEntry[] = [...server, ...browser.filter((p) => !known.has(p.id))];
  return merged.sort((a, b) => Date.parse(b.last_active_at) - Date.parse(a.last_active_at) || a.title.localeCompare(b.title));
}

export type LibraryView = "all" | "uploaded" | "workspaces" | "needs-analysis";
export type LibrarySort = "recent" | "title" | "year";

export const LIBRARY_VIEWS: { value: LibraryView; label: string }[] = [
  { value: "all", label: "All" },
  { value: "uploaded", label: "Uploaded" },
  { value: "workspaces", label: "In a workspace" },
  { value: "needs-analysis", label: "Not analysed" },
];

export const LIBRARY_SORTS: { value: LibrarySort; label: string }[] = [
  { value: "recent", label: "Recent activity" },
  { value: "title", label: "Title" },
  { value: "year", label: "Newest published" },
];

function inView(entry: LibraryEntry, view: LibraryView): boolean {
  switch (view) {
    case "uploaded":
      return entry.roles.includes("uploaded");
    case "workspaces":
      return entry.workspaces.length > 0;
    case "needs-analysis":
      return entry.analyzed === false;
    default:
      return true;
  }
}

/** How many papers each view holds, for its chip. */
export function viewCounts(entries: LibraryEntry[]): Record<LibraryView, number> {
  return {
    all: entries.length,
    uploaded: entries.filter((e) => inView(e, "uploaded")).length,
    workspaces: entries.filter((e) => inView(e, "workspaces")).length,
    "needs-analysis": entries.filter((e) => inView(e, "needs-analysis")).length,
  };
}

/** Words of the query that each must appear in the paper's title, authors, venue, publisher or DOI. */
export function filterLibrary(entries: LibraryEntry[], view: LibraryView, query: string): LibraryEntry[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return entries.filter((e) => {
    if (!inView(e, view)) return false;
    if (words.length === 0) return true;
    const hay = [e.title, ...e.authors, e.venue ?? "", e.publisher ?? "", e.doi ?? "", e.id].join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

export function sortLibrary(entries: LibraryEntry[], sort: LibrarySort): LibraryEntry[] {
  const out = [...entries];
  if (sort === "title") out.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  else if (sort === "year") out.sort((a, b) => (b.year ?? -Infinity) - (a.year ?? -Infinity) || a.title.localeCompare(b.title));
  // "recent" keeps mergeLibrary's order
  return out;
}

const ROLE_LABEL: Record<LibraryRole, string> = {
  uploaded: "Uploaded",
  seed: "Workspace seed",
  searched: "Searched from",
  analyzed: "Analysed",
  collected: "Collected",
};

/** How the paper came to be in the library, in words ("Uploaded · Searched from"). */
export function rolesLine(entry: LibraryEntry): string {
  const roles = entry.roles.filter((r) => r !== "analyzed").map((r) => ROLE_LABEL[r]);
  if (entry.onlyInThisBrowser) roles.push("in this browser");
  return roles.join(" · ");
}

/** The one action that moves this paper forward: analyse it, see its results, or discover around it. */
export function nextStep(entry: LibraryEntry): { label: string; href: string } {
  if (entry.last_run_id) return { label: "Open results", href: `/discover/${entry.id}?run=${entry.last_run_id}` };
  if (entry.analyzed) return { label: "Discover related", href: `/discover/${entry.id}` };
  return { label: entry.analyzed === false ? "Analyse" : "Open", href: `/papers/${entry.id}` };
}
