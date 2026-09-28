import { describe, expect, it } from "vitest";
import type { UsageTotals } from "@/lib/api/types";
import { billingConsoles, compactTokens, featureLabel, formatTokens, rangeLabel, shareOf, usageCaveats } from "./usage";

const zero: UsageTotals = {
  calls: 0,
  failed_calls: 0,
  unreported_calls: 0,
  prompt_tokens: 0,
  cached_prompt_tokens: 0,
  completion_tokens: 0,
  reasoning_tokens: 0,
  total_tokens: 0,
};

describe("token figures", () => {
  it("are exact in tables and compact only at a glance", () => {
    expect(formatTokens(48_210)).toBe("48,210");
    expect(compactTokens(9_940)).toBe("9,940");
    expect(compactTokens(48_210)).toBe("48.2K");
    expect(compactTokens(1_250_000)).toBe("1.3M");
  });

  it("gives a share of nothing as none", () => {
    expect(shareOf(25, 100)).toBe(0.25);
    expect(shareOf(5, 0)).toBe(0);
  });
});

describe("featureLabel", () => {
  it("names what a call was for in the app's words", () => {
    expect(featureLabel("gaps")).toBe("Research gaps");
    expect(featureLabel("other")).toBe("Unlabelled");
    expect(featureLabel("new_thing")).toBe("New thing");
  });
});

describe("rangeLabel", () => {
  const opts = { timeZone: "UTC", locale: "en-US", now: Date.UTC(2026, 8, 28) };

  it("says which window the numbers cover, and from when", () => {
    const month = rangeLabel(
      { range: { key: "30d", days: 30, since: "2026-08-29T09:30:00+00:00", until: "2026-09-28T09:30:00+00:00" }, first_call_at: null },
      opts,
    );
    expect(month.text).toBe("Last 30 days, since Aug 29");
    expect(month.exact).toMatch(/Aug 29, 2026.*9:30/);
  });

  it("dates all time from the first call, and says nothing it doesn't know", () => {
    const all = { range: { key: "all" as const, days: null, since: null, until: "2026-09-28T09:30:00Z" } };
    expect(rangeLabel({ ...all, first_call_at: "2026-09-27T00:38:42Z" }, opts).text).toBe("All time, since Sep 27");
    expect(rangeLabel({ ...all, first_call_at: null }, opts)).toEqual({ text: "All time", exact: null });
  });
});

describe("usageCaveats", () => {
  it("says what the totals leave out, and nothing when nothing is", () => {
    expect(usageCaveats(zero)).toEqual([]);
    expect(usageCaveats({ ...zero, calls: 3, failed_calls: 1, unreported_calls: 2 })).toEqual([
      "1 call failed and reported no tokens; it is counted as calls only.",
      "2 answered calls came back without usage from the provider, so their tokens are missing from these totals.",
    ]);
  });
});

describe("billingConsoles", () => {
  it("points to each provider used, once, most-used first", () => {
    const row = (provider: string, model: string) => ({ ...zero, provider, model });
    expect(billingConsoles({ by_model: [row("deepseek", "deepseek-flash"), row("gemini", "g"), row("deepseek", "deepseek-v4-pro")] }).map((c) => c.name)).toEqual([
      "DeepSeek",
      "Gemini",
    ]);
  });
});
