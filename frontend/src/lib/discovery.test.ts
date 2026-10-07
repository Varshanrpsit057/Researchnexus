import { describe, expect, it } from "vitest";
import type { DiscoveryReport, Job } from "@/lib/api/types";
import {
  discoveryProgress,
  formatSeconds,
  headline,
  runIssues,
  runState,
  sourceSummary,
  stepDetail,
  stepTiming,
  strategyNote,
} from "./discovery";

const job = (over: Partial<Job>): Job => ({
  job_id: "job_1",
  owner_id: "usr_1",
  workspace_id: null,
  kind: "discover",
  status: "running",
  progress: {},
  result_ref: null,
  error: null,
  created_at: "2026-10-01T10:00:00+00:00",
  updated_at: "2026-10-01T10:00:05+00:00",
  ...over,
});

const report = (over: Partial<DiscoveryReport>): DiscoveryReport => ({
  started_at: "2026-10-01T10:00:00+00:00",
  elapsed_s: 30,
  steps: {},
  strategies: {},
  sources: {},
  warnings: [],
  ...over,
});

describe("discovery progress", () => {
  it("reads a live job's structured progress, and nothing from an older flat one", () => {
    const live = discoveryProgress({ stage: "discovery", step: "search", found: 12, preview: [], steps: { search: { state: "running" } }, strategies: {}, sources: {}, warnings: [], started_at: "x", elapsed_s: 3 });
    expect(live?.found).toBe(12);
    expect(discoveryProgress({ stage: "ranking" })).toBeNull();
    expect(discoveryProgress(undefined)).toBeNull();
  });

  it("names what the run is doing, keeping the older stage wording", () => {
    expect(headline(null, "ranking")).toBe("Ranking candidates against the seed profile…");
    expect(headline(null, "discovery")).toBe("Searching external sources…");
    expect(headline(discoveryProgress({ stage: "discovery", step: "resolve", steps: {}, found: 0, preview: [] }), "discovery")).toBe(
      "Looking the seed paper up on OpenAlex and Semantic Scholar…",
    );
    expect(headline(null, undefined)).toBe("Starting…");
  });

  it("tells a finished, failed, cancelled and interrupted run apart", () => {
    expect(runState(undefined)).toBe("starting");
    expect(runState(job({ status: "queued" }))).toBe("running");
    expect(runState(job({ status: "partial", result_ref: "run_1" }))).toBe("done");
    expect(runState(job({ status: "failed", error: "The search step failed: boom" }))).toBe("failed");
    expect(runState(job({ status: "failed", progress: { stage: "interrupted" } }))).toBe("interrupted");
    expect(runState(job({ status: "cancelled" }))).toBe("cancelled");
  });

  it("gives each step's measured time, or the limit a running step has left", () => {
    expect(stepTiming({ state: "done", seconds: 4.14 }, 20)).toBe("4.1 s");
    expect(stepTiming({ state: "running", started_s: 5, limit_s: 30 }, 12.2)).toBe("stops within 23 s");
    expect(stepTiming({ state: "running", started_s: 5, limit_s: 30 }, 36)).toBe("stopping");
    expect(stepTiming({ state: "running", started_s: 5 }, 9)).toBeNull();
    expect(stepTiming({ state: "pending" }, 9)).toBeNull();
    expect(formatSeconds(75)).toBe("1 min 15 s");
  });

  it("says what each step produced", () => {
    expect(stepDetail("plan", { state: "done", note: "model" }, 0)).toBe("Written by your model");
    expect(stepDetail("plan", { state: "done", note: "fallback" }, 0)).toBe("Built from the paper's profile");
    expect(stepDetail("resolve", { state: "done", note: "found on OpenAlex and Semantic Scholar" }, 0)).toBe("Found on OpenAlex and Semantic Scholar");
    expect(stepDetail("search", { state: "running" }, 142)).toBe("142 papers so far");
    expect(stepDetail("search", { state: "done", found: 452 }, 452)).toBe("452 papers found");
    expect(stepDetail("score", { state: "running", total: 238 }, 0)).toBe("238 records of the papers kept");
    expect(stepDetail("rank", { state: "done", ranked: 190, off_topic: 10 }, 0)).toBe("190 ranked · 10 set aside as off-topic");
    expect(stepDetail("trail", { state: "done", edges: 40 }, 0)).toBe("40 connections proposed");
    expect(stepDetail("search", { state: "failed", note: "The discovery step failed: boom" }, 0)).toBe("The discovery step failed: boom");
  });

  it("explains each strategy's outcome from what it recorded", () => {
    expect(strategyNote("citation", { state: "timed_out", found: 40, seconds: 30 })).toBe("Stopped at its 30 s limit; the 40 papers it had found are kept");
    expect(strategyNote("recommendation", { state: "done", found: 0, notes: ["recommendation_no_seed_id"] })).toBe(
      "Nothing to start from: the seed wasn't found on OpenAlex or Semantic Scholar",
    );
    expect(strategyNote("citation", { state: "done", found: 33, notes: ["citation_cites_seed_failed"] })).toBe("Couldn't fetch the papers citing the seed");
    expect(strategyNote("keyword", { state: "done", found: 0, notes: ["keyword_all_sources_failed"] })).toBe("Every source it asked failed");
    expect(strategyNote("keyword", { state: "done", found: 194 })).toBeNull();
    expect(strategyNote("keyword", { state: "failed", found: 0, notes: ["keyword_timed_out"] })).toBe("Ran out of time before anything came back");
  });

  it("counts each source's answers and failures", () => {
    expect(sourceSummary({ answered: 16, failed: 0, cached: 0 })).toBe("16 answered");
    expect(sourceSummary({ answered: 3, failed: 4, cached: 2, last_failure: "rate_limited" })).toBe("3 answered · 2 reused · 4 refused (rate-limited)");
    expect(sourceSummary({ answered: 0, failed: 11, cached: 0, last_failure: "http_503" })).toBe("11 refused (unavailable, HTTP 503)");
  });
});

describe("what a saved run is missing", () => {
  it("lists what didn't finish, and why", () => {
    const issues = runIssues(
      report({
        strategies: { citation: { state: "timed_out", found: 40, seconds: 30 }, keyword: { state: "failed", found: 0, notes: ["keyword_error"] } },
        sources: { semantic_scholar: { answered: 4, failed: 4, cached: 0, last_failure: "rate_limited" }, arxiv: { answered: 5, failed: 0, cached: 0 } },
        warnings: ["search_plan_fallback_timeout"],
      }),
      { after_dedupe: 300 },
    );
    expect(issues.incomplete).toEqual([
      "Keyword search failed.",
      "Citations ran out of time after 30 s; the 40 papers it had found are included.",
      "Semantic Scholar refused 4 of 8 requests (rate-limited).",
      "The model took too long to write the search plan, so the plan built from the paper's profile was used.",
    ]);
  });

  it("says a capped run kept its best-evidenced papers, without calling it incomplete", () => {
    const issues = runIssues(report({ steps: { save: { state: "done", total: 200 } }, warnings: ["budget_truncated"] }), { after_dedupe: 624 });
    expect(issues.incomplete).toEqual([]);
    expect(issues.notes).toEqual(["Kept the 200 papers with the most evidence of the 624 found; the rest weren't ranked."]);
  });

  it("says when the seed isn't on the sources citations start from", () => {
    const issues = runIssues(report({ steps: { resolve: { state: "done", note: "not found on OpenAlex or Semantic Scholar" } } }), { after_dedupe: 10 });
    expect(issues.notes).toEqual(["The seed isn't on OpenAlex or Semantic Scholar, so it had no citations or recommendations to follow."]);
  });
});
