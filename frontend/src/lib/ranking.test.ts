import { afterEach, describe, expect, it } from "vitest";
import type { RankingExplanation } from "@/lib/api/types";
import {
  CRITERIA,
  DEFAULT_CRITERIA,
  bandReason,
  criteriaError,
  criteriaName,
  criteriaShares,
  explainRank,
  readCriteria,
  sameCriteria,
  writeCriteria,
} from "./ranking";

afterEach(() => window.localStorage.clear());

describe("ranking criteria", () => {
  it("defaults to the initial weights plus a preferred publisher", () => {
    expect(DEFAULT_CRITERIA).toEqual({ topic: 42, problem: 18, methods: 14, datasets: 8, citations: 12, recency: 6, publisher: 15 });
    expect(CRITERIA.map((c) => c.key)).toEqual(["topic", "problem", "methods", "datasets", "citations", "recency", "publisher"]);
  });

  it("says each criterion's share of the score, from proportions alone", () => {
    expect(criteriaShares({ topic: 2, problem: 1, methods: 1, datasets: 0, citations: 0, recency: 0, publisher: 0 })).toEqual({
      topic: 50, problem: 25, methods: 25, datasets: 0, citations: 0, recency: 0, publisher: 0,
    });
  });

  it("refuses criteria the backend would refuse", () => {
    expect(criteriaError(DEFAULT_CRITERIA)).toBeNull();
    expect(criteriaError({ topic: 0, problem: 0, methods: 0, datasets: 0, citations: 0, recency: 0, publisher: 0 })).toBe(
      "At least one criterion has to count.",
    );
    expect(criteriaError({ ...DEFAULT_CRITERIA, recency: 101 })).toBe("Each criterion is a whole number from 0 to 100.");
    expect(criteriaError({ ...DEFAULT_CRITERIA, recency: 2.5 })).toBe("Each criterion is a whole number from 0 to 100.");
  });

  it("is kept in this browser, and a damaged or missing value reads as the defaults", () => {
    expect(readCriteria()).toEqual(DEFAULT_CRITERIA);
    const mine = { topic: 70, problem: 10, methods: 10, datasets: 0, citations: 10, recency: 0, publisher: 0 };
    expect(writeCriteria(mine)).toBe(true);
    expect(readCriteria()).toEqual(mine);
    // criteria saved before the publisher criterion existed keep their values and gain its default
    const older = { topic: 70, problem: 10, methods: 10, datasets: 0, citations: 10, recency: 0 };
    window.localStorage.setItem("researchnexus.pref.rankingCriteria", JSON.stringify(older));
    expect(readCriteria()).toEqual({ ...older, publisher: 15 });
    window.localStorage.setItem("researchnexus.pref.rankingCriteria", "{not json");
    expect(readCriteria()).toEqual(DEFAULT_CRITERIA);
    window.localStorage.setItem("researchnexus.pref.rankingCriteria", JSON.stringify({ ...mine, topic: -1 }));
    expect(readCriteria()).toEqual(DEFAULT_CRITERIA);
    expect(sameCriteria(mine, { ...mine })).toBe(true);
    expect(sameCriteria(mine, DEFAULT_CRITERIA)).toBe(false);
  });
});

describe("naming a ranking's criteria", () => {
  it("tells the defaults, the initial weights (before the publisher preference) and the reader's own apart", () => {
    expect(criteriaName(DEFAULT_CRITERIA)).toBe("the default weights");
    expect(criteriaName({ ...DEFAULT_CRITERIA, publisher: 0 })).toBe("the initial weights");
    expect(criteriaName({ ...DEFAULT_CRITERIA, recency: 50 })).toBe("your weights");
  });
});

describe("why a paper ranks where it does", () => {
  const explanation: RankingExplanation = {
    bullet_reasons: [],
    prose: "",
    signals_used: [],
    template_only: true,
    contributions: [
      { signal: "semantic_doc", value: 0.9, weight: 0.5, contribution: 0.45 },
      { signal: "citation", value: 1, weight: 0.3, contribution: 0.3 },
      { signal: "recency", value: 0.2, weight: 0.2, contribution: 0.04 },
    ],
    missing_signals: ["semantic_chunk", "dataset_overlap"],
  };

  it("lists each signal's value, weight, contribution and share of the score", () => {
    const why = explainRank(explanation, 0.79);
    expect(why.rows.map((r) => [r.label, r.criterion, r.share])).toEqual([
      ["Topic similarity (whole paper)", "topic", 57],
      ["Citation link to the seed", "citations", 38],
      ["Recency", "recency", 5],
    ]);
    expect(why.missing).toEqual(["Topic similarity (passages)", "Datasets"]);
  });

  it("says nothing it can't back up for a ranking saved without contributions", () => {
    expect(explainRank({ ...explanation, contributions: undefined, missing_signals: undefined }, 0.5)).toEqual({ rows: [], missing: [] });
  });

  it("explains a band from the real thresholds", () => {
    expect(bandReason(0.71, "high", { high: 0.66, medium: 0.33 })).toBe("Score 0.71: high starts at 0.66.");
    expect(bandReason(0.4, "medium", { high: 0.66, medium: 0.33 })).toBe("Score 0.40: medium is 0.33 up to 0.66.");
    expect(bandReason(0.1, "low", { high: 0.66, medium: 0.33 })).toBe("Score 0.10: low is below 0.33.");
  });
});
