import type {
  ComparisonResponse,
  GroupedTrail,
  RelatedResult,
  ResearchDirection,
  ResearchGap,
  WorkspacePaper,
} from "@/lib/api/types";

/** One request's lifecycle, so "still loading", "failed", and "loaded but
 * empty" can never be confused with each other when deciding what a stage
 * of the research path honestly claims. */
export type Loadable<T> = { status: "loading" } | { status: "error" } | { status: "ready"; data: T };

export type StationKey = "papers" | "trail" | "compare" | "gaps" | "directions";
export type StationState = "done" | "review" | "todo" | "loading" | "error";

export interface Station {
  key: StationKey;
  label: string;
  /** Sub-route under /workspaces/[id]/ where this stage's real work lives. */
  slug: string;
  state: StationState;
  value: string;
  detail: string;
  /** What to do next, when this stage is the next step. */
  action: string;
}

export interface ProgressInputs {
  papers: WorkspacePaper[];
  trail: Loadable<GroupedTrail>;
  /** `null` means no comparison has been run yet (the API's 404). */
  comparison: Loadable<ComparisonResponse | null>;
  gaps: Loadable<ResearchGap[]>;
  directions: Loadable<ResearchDirection[]>;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

type StationCopy = Pick<Station, "key" | "label" | "slug" | "action">;

function pending(copy: StationCopy, state: "loading" | "error"): Station {
  return {
    ...copy,
    state,
    value: state === "loading" ? "Loading…" : "Unavailable",
    detail: state === "loading" ? "" : "Could not load",
  };
}

/** The workspace's research path, derived only from real API data: each
 * stage is "done" once it has reviewed output, "review" when it has output
 * still awaiting a decision, and "todo" when nothing exists yet. */
export function buildStations(input: ProgressInputs): Station[] {
  const related = input.papers.filter((p) => p.role !== "seed").length;
  const papers: Station = {
    key: "papers",
    label: "Papers",
    slug: "papers",
    state: related > 0 ? "done" : "todo",
    value: plural(input.papers.length, "paper"),
    detail: related > 0 ? `${related} related to the seed` : "Only the seed so far",
    action: "Add related papers",
  };

  const trailCopy: StationCopy = { key: "trail", label: "Connections", slug: "trail", action: "Review connections" };
  let trail: Station;
  if (input.trail.status !== "ready") {
    trail = pending(trailCopy, input.trail.status);
  } else {
    const entries = Object.values(input.trail.data.groups).flat();
    const awaiting = entries.filter((e) => e.edge.user_state === "pending").length;
    trail = {
      ...trailCopy,
      state: entries.length === 0 ? "todo" : awaiting > 0 ? "review" : "done",
      value: entries.length === 0 ? "None yet" : plural(entries.length, "connection"),
      detail:
        entries.length === 0
          ? "Typed relationships to the seed"
          : awaiting > 0
            ? `${awaiting} awaiting review`
            : "All reviewed",
      action: entries.length === 0 ? "Explore the trail" : "Review connections",
    };
  }

  const compareCopy: StationCopy = { key: "compare", label: "Comparison", slug: "compare", action: "Compare papers" };
  let compare: Station;
  if (input.comparison.status !== "ready") {
    compare = pending(compareCopy, input.comparison.status);
  } else if (input.comparison.data === null) {
    compare = {
      ...compareCopy,
      state: "todo",
      value: "Not run yet",
      detail: related > 0 ? "Line papers up field by field" : "Needs a second paper",
    };
  } else {
    const c = input.comparison.data;
    compare = {
      ...compareCopy,
      state: "done",
      value: plural(c.schema.length, "field"),
      detail: `${plural(c.paper_ids.length, "paper")} · ${Math.round(c.coverage * 100)}% evidence-grounded`,
    };
  }

  const gapsCopy: StationCopy = { key: "gaps", label: "Gaps", slug: "gaps", action: "Find gaps" };
  let gaps: Station;
  let acceptedGaps = 0;
  if (input.gaps.status !== "ready") {
    gaps = pending(gapsCopy, input.gaps.status);
  } else {
    const all = input.gaps.data;
    acceptedGaps = all.filter((g) => g.user_state === "accepted").length;
    const toReview = all.filter((g) => g.user_state === "candidate").length;
    if (all.length === 0) {
      gaps = { ...gapsCopy, state: "todo", value: "None yet", detail: "Evidence-grounded gaps across papers" };
    } else if (acceptedGaps > 0) {
      gaps = { ...gapsCopy, state: "done", value: `${acceptedGaps} accepted`, detail: `${all.length} found` };
    } else if (toReview > 0) {
      gaps = { ...gapsCopy, state: "review", value: plural(all.length, "gap"), detail: `${toReview} to review`, action: "Review gaps" };
    } else {
      gaps = { ...gapsCopy, state: "todo", value: plural(all.length, "gap"), detail: "None accepted" };
    }
  }

  const directionsCopy: StationCopy = { key: "directions", label: "Directions", slug: "directions", action: "Develop directions" };
  let directions: Station;
  if (input.directions.status !== "ready") {
    directions = pending(directionsCopy, input.directions.status);
  } else {
    const all = input.directions.data;
    const accepted = all.filter((d) => d.user_state === "accepted").length;
    const toReview = all.filter((d) => d.user_state === "candidate").length;
    if (all.length === 0) {
      directions = {
        ...directionsCopy,
        state: "todo",
        value: "None yet",
        detail: acceptedGaps > 0 ? "Turn an accepted gap into a direction" : "Needs an accepted gap first",
      };
    } else if (accepted > 0) {
      directions = { ...directionsCopy, state: "done", value: `${accepted} accepted`, detail: `${all.length} proposed` };
    } else if (toReview > 0) {
      directions = {
        ...directionsCopy,
        state: "review",
        value: plural(all.length, "direction"),
        detail: `${toReview} to review`,
        action: "Review directions",
      };
    } else {
      directions = { ...directionsCopy, state: "todo", value: plural(all.length, "direction"), detail: "None accepted" };
    }
  }

  return [papers, trail, compare, gaps, directions];
}

/** The first stage still needing work -- but only once every stage before
 * it has actually loaded, so the page never recommends a later step while
 * an earlier one's real state is still unknown. */
export function nextStation(stations: Station[]): Station | null {
  for (const s of stations) {
    if (s.state === "loading" || s.state === "error") return null;
    if (s.state === "todo" || s.state === "review") return s;
  }
  return null;
}

/** Results from the workspace's own discovery run that are not members yet. */
export function addableFromRun(results: RelatedResult[], papers: WorkspacePaper[]): RelatedResult[] {
  const members = new Set(papers.map((p) => p.paper_id));
  return results.filter((r) => !members.has(r.paper.id));
}
