import { ApiError } from "@/lib/api/client";
import { workspaces } from "@/lib/api/endpoints";
import type { CellStatus, ComparisonCell, ComparisonResponse } from "@/lib/api/types";

/** The latest comparison, or null when none has been run (the API's 404). */
export async function latestComparisonOrNull(workspaceId: string): Promise<ComparisonResponse | null> {
  try {
    return await workspaces.getLatestComparison(workspaceId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/** The fields the backend derives a default schema from, in its order. */
export const CANONICAL_FIELDS = ["problem", "method", "dataset", "metric", "result", "limitation"] as const;

const FIELD_LABEL: Record<string, string> = {
  problem: "Research problem",
  method: "Method",
  dataset: "Datasets",
  metric: "Metrics",
  result: "Results",
  limitation: "Limitations",
};

export function fieldLabel(field: string): string {
  return FIELD_LABEL[field] ?? field.charAt(0).toUpperCase() + field.slice(1);
}

/** The backend's own column normalisation (app/services/synthesis/compare.py). */
export function normalizeField(input: string): string {
  return input.replace(/\s+/g, " ").trim().toLowerCase().slice(0, 40);
}

/** A cell's state, read the same way for cells stored before statuses existed. */
export function cellStatus(cell: ComparisonCell | undefined): CellStatus {
  if (!cell) return "unknown";
  if (cell.text != null && cell.span != null) return "found";
  return cell.status && cell.status !== "found" ? cell.status : "unknown";
}

/** How each empty state reads: a short label, and what it means. */
export const CELL_COPY: Record<Exclude<CellStatus, "found">, { label: string; meaning: string }> = {
  not_stated: { label: "Not stated", meaning: "The paper's text was read and does not state this." },
  unsupported: {
    label: "Unverified",
    meaning: "A value was proposed, but no passage in the paper states it word for word, so it isn't shown.",
  },
  no_text: { label: "No text to read", meaning: "This paper has no text in the workspace, not even an abstract." },
  not_extracted: { label: "Not read", meaning: "Reading this paper failed during the comparison. Comparing again may fix it." },
  unknown: { label: "Not found", meaning: "No value was found. This comparison predates the reason being recorded." },
};

export interface Coverage {
  found: number;
  total: number;
}

/** Cells found in the papers' text, over the papers shown. */
export function coverageOf(comparison: ComparisonResponse, paperIds: string[]): Coverage {
  let found = 0;
  let total = 0;
  for (const row of comparison.rows) {
    if (!paperIds.includes(row.paper_id)) continue;
    for (const field of comparison.schema) {
      total += 1;
      if (cellStatus(row.cells[field]) === "found") found += 1;
    }
  }
  return { found, total };
}

/** Selected papers the comparison doesn't cover yet (running again includes them). */
export function notYetCompared(comparison: ComparisonResponse | null, selected: string[]): string[] {
  const covered = new Set(comparison?.paper_ids ?? []);
  return selected.filter((p) => !covered.has(p));
}

/** Papers of a comparison that are no longer in the workspace. */
export function leftWorkspace(comparison: ComparisonResponse, members: string[]): string[] {
  return comparison.paper_ids.filter((p) => !members.includes(p));
}
