import { beforeEach, describe, expect, it } from "vitest";
import type { ApiKeySummary } from "@/lib/api/types";
import { readPreference, writePreference } from "./preferences";
import { activeSummary, budgetOf, describeTest, parseCap, providerRows, usd } from "./settings";

const key = (provider: ApiKeySummary["provider"], status: ApiKeySummary["status"]): ApiKeySummary => ({
  provider,
  status,
  key_last4: "9z8y",
  checked_at: "2026-09-26T10:00:00Z",
});

describe("providers", () => {
  it("lists every allowed provider with its saved key, default and active marks", () => {
    const rows = providerRows([key("groq", "working"), key("openai", "failed")], { default_provider: "openai", active_provider: "groq" });
    expect(rows.map((r) => [r.id, r.status, r.isDefault, r.isActive])).toEqual([
      ["openai", "failed", true, false],
      ["groq", "working", false, true],
      ["deepseek", "none", false, false],
      ["openrouter", "none", false, false],
      ["together", "none", false, false],
      ["gemini", "none", false, false],
    ]);
  });

  it("says which provider is in use and why", () => {
    expect(activeSummary({ default_provider: null, active_provider: null })?.tone).toBe("warn");
    expect(activeSummary({ default_provider: "openai", active_provider: "groq" })?.text).toBe(
      "Your default, OpenAI, has no working key right now, so Groq is used instead.",
    );
    expect(activeSummary({ default_provider: "groq", active_provider: "groq" })?.text).toBe(
      "Chat, comparison, gap finding and directions use Groq, your default.",
    );
    expect(activeSummary({ default_provider: null, active_provider: "groq" })?.text).toContain("the first working key you saved");
  });

  it("describes a key test without the key", () => {
    expect(describeTest({ success: true, latency_ms: 480, capabilities: { json_mode: true, context_tokens: 131072, streaming: true } })).toBe(
      "It works: answered in 480 ms, JSON mode, a 131,072-token context, streaming.",
    );
    expect(describeTest({ success: false, message: "invalid api key" })).toBe("It failed: invalid api key.");
  });
});

describe("workspace budgets", () => {
  it("reads estimated spend against the cap", () => {
    expect(budgetOf({ cost_used_usd: 1.25, token_budget_usd: 5, tokens_used: { prompt: 900, completion: 100 } })).toEqual({
      used: 1.25,
      cap: 5,
      fraction: 0.25,
      reached: false,
      tokens: 1000,
    });
    expect(budgetOf({ cost_used_usd: 6, token_budget_usd: 5, tokens_used: { prompt: 0, completion: 0 } }).reached).toBe(true);
    expect(usd(0.004)).toBe("<$0.01");
  });

  it("accepts only a positive cap", () => {
    expect(parseCap("$7.5")).toBe(7.5);
    expect(parseCap("0")).toBeNull();
    expect(parseCap("-2")).toBeNull();
    expect(parseCap("ten")).toBeNull();
  });
});

describe("preferences", () => {
  beforeEach(() => window.localStorage.clear());

  it("round-trips an allowed value and ignores anything else", () => {
    expect(readPreference("backgroundMotion")).toBe("moving");
    writePreference("backgroundMotion", "still");
    expect(readPreference("backgroundMotion")).toBe("still");
    window.localStorage.setItem("researchnexus.pref.referenceStyle", "chicago");
    expect(readPreference("referenceStyle")).toBe("apa");
  });
});
