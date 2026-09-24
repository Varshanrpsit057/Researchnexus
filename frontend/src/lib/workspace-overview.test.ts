import { describe, expect, it } from "vitest";
import type {
  ComparisonResponse,
  GroupedTrail,
  RelatedResult,
  ResearchDirection,
  ResearchGap,
  TrailGroupEntry,
  WorkspacePaper,
} from "@/lib/api/types";
import { addableFromRun, buildStations, nextStation, timeAgo, type Loadable } from "./workspace-overview";

function paper(id: string, role: "seed" | "related"): WorkspacePaper {
  return {
    workspace_id: "ws_1",
    paper_id: id,
    added_by: role === "seed" ? "manual" : "trail",
    role,
    grounding: "full_text",
    pinned: false,
    tags: [],
    note: null,
    order: 0,
    ranking_snapshot: null,
    added_at: "2026-09-01T00:00:00Z",
  };
}

function trailWith(states: ("pending" | "accepted")[]): GroupedTrail {
  const entries = states.map(
    (user_state, i) => ({ target: { id: `pap_${i}`, title: null, year: null }, edge: { user_state } }) as unknown as TrailGroupEntry,
  );
  return {
    seed_paper_id: "pap_seed",
    groups: {
      SIMILAR: entries,
      FOUNDATIONAL: [],
      RECENT: [],
      COMPETING: [],
      METHOD_EXTENSION: [],
      DATASET_RELATED: [],
      POTENTIALLY_CONTRADICTORY: [],
    },
  };
}

const gap = (user_state: ResearchGap["user_state"]) => ({ user_state }) as ResearchGap;
const direction = (user_state: ResearchDirection["user_state"]) => ({ user_state }) as ResearchDirection;
const ready = <T,>(data: T): Loadable<T> => ({ status: "ready", data });
const loading = { status: "loading" } as const;

const allReady = {
  papers: [paper("pap_seed", "seed"), paper("pap_2", "related")],
  trail: ready(trailWith(["accepted"])),
  comparison: ready<ComparisonResponse | null>({
    comparison_id: "cmp_1",
    schema: ["method", "dataset"],
    generated_by: "llm",
    paper_ids: ["pap_seed", "pap_2"],
    rows: [],
    coverage: 0.75,
    decontext_eval: null,
  }),
  gaps: ready([gap("accepted"), gap("candidate")]),
  directions: ready([direction("accepted")]),
};

const byKey = (stations: ReturnType<typeof buildStations>) => Object.fromEntries(stations.map((s) => [s.key, s]));

describe("buildStations", () => {
  it("reports every stage done, with real numbers, once each has reviewed output", () => {
    const s = byKey(buildStations(allReady));
    expect(s.papers).toMatchObject({ state: "done", value: "2 papers", detail: "1 related to the seed" });
    expect(s.trail).toMatchObject({ state: "done", value: "1 connection", detail: "All reviewed" });
    expect(s.compare).toMatchObject({ state: "done", value: "2 fields", detail: "2 papers · 75% evidence-grounded" });
    expect(s.gaps).toMatchObject({ state: "done", value: "1 accepted", detail: "2 found" });
    expect(s.directions).toMatchObject({ state: "done", value: "1 accepted" });
    expect(nextStation(buildStations(allReady))).toBeNull();
  });

  it("marks a workspace with only its seed as needing related papers first", () => {
    const stations = buildStations({ ...allReady, papers: [paper("pap_seed", "seed")] });
    expect(byKey(stations).papers).toMatchObject({ state: "todo", value: "1 paper", detail: "Only the seed so far" });
    expect(nextStation(stations)?.key).toBe("papers");
  });

  it("flags pending trail connections as needing review, not done", () => {
    const stations = buildStations({ ...allReady, trail: ready(trailWith(["pending", "accepted", "pending"])) });
    expect(byKey(stations).trail).toMatchObject({ state: "review", value: "3 connections", detail: "2 awaiting review" });
    expect(nextStation(stations)).toMatchObject({ key: "trail", action: "Review connections" });
  });

  it("treats a missing comparison (null) as not run, not as an error", () => {
    const stations = buildStations({ ...allReady, comparison: ready(null) });
    expect(byKey(stations).compare).toMatchObject({ state: "todo", value: "Not run yet" });
    expect(nextStation(stations)?.key).toBe("compare");
  });

  it("separates candidate gaps awaiting review from accepted ones", () => {
    const stations = buildStations({ ...allReady, gaps: ready([gap("candidate"), gap("candidate"), gap("rejected")]) });
    expect(byKey(stations).gaps).toMatchObject({ state: "review", value: "3 gaps", detail: "2 to review" });
  });

  it("explains that directions need an accepted gap first", () => {
    const stations = buildStations({ ...allReady, gaps: ready([]), directions: ready([]) });
    const s = byKey(stations);
    expect(s.gaps).toMatchObject({ state: "todo", value: "None yet" });
    expect(s.directions).toMatchObject({ state: "todo", value: "None yet", detail: "Needs an accepted gap first" });
  });

  it("never names a next step past a stage whose data is still loading", () => {
    const stations = buildStations({ ...allReady, trail: loading, comparison: ready(null) });
    expect(byKey(stations).trail.state).toBe("loading");
    expect(nextStation(stations)).toBeNull();
  });

  it("surfaces a failed load as unavailable rather than inventing a state", () => {
    const stations = buildStations({ ...allReady, gaps: { status: "error" } });
    expect(byKey(stations).gaps).toMatchObject({ state: "error", value: "Unavailable" });
  });
});

describe("addableFromRun", () => {
  it("offers only run results that are not already in the workspace", () => {
    const result = (id: string) => ({ paper: { id } }) as RelatedResult;
    const addable = addableFromRun([result("pap_seed"), result("pap_2"), result("pap_3")], [paper("pap_seed", "seed"), paper("pap_2", "related")]);
    expect(addable.map((r) => r.paper.id)).toEqual(["pap_3"]);
  });
});

describe("timeAgo", () => {
  const now = Date.parse("2026-09-23T12:00:00Z");
  it("reads recent times in plain relative terms", () => {
    expect(timeAgo("2026-09-23T11:59:40Z", now)).toBe("just now");
    expect(timeAgo("2026-09-23T11:55:00Z", now)).toBe("5 min ago");
    expect(timeAgo("2026-09-23T09:00:00Z", now)).toBe("3 h ago");
    expect(timeAgo("2026-09-21T12:00:00Z", now)).toBe("2 d ago");
  });
});
