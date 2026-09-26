import type { ApiKeyStatus, ApiKeySummary, LlmProvider, LlmTestResult, MeResponse, Workspace } from "@/lib/api/types";

/** The backend's fixed allowlist (app/domain/user.py::LlmProvider), in display order. */
export const PROVIDERS: { id: LlmProvider; name: string }[] = [
  { id: "openai", name: "OpenAI" },
  { id: "groq", name: "Groq" },
  { id: "deepseek", name: "DeepSeek" },
  { id: "openrouter", name: "OpenRouter" },
  { id: "together", name: "Together" },
  { id: "gemini", name: "Gemini" },
];

export const providerName = (id: LlmProvider | string | null | undefined): string =>
  PROVIDERS.find((p) => p.id === id)?.name ?? (id ? String(id) : "");

export const STATUS_COPY: Record<ApiKeyStatus | "none", string> = {
  working: "Working",
  failed: "Failed its last check",
  unverified: "Not checked yet",
  none: "No key",
};

export interface ProviderRow {
  id: LlmProvider;
  name: string;
  key: ApiKeySummary | null;
  status: ApiKeyStatus | "none";
  isDefault: boolean;
  isActive: boolean;
}

/** Every provider the backend allows, each with its saved key (if any). */
export function providerRows(keys: ApiKeySummary[], me: Pick<MeResponse, "default_provider" | "active_provider"> | undefined): ProviderRow[] {
  return PROVIDERS.map(({ id, name }) => {
    const key = keys.find((k) => k.provider === id) ?? null;
    return {
      id,
      name,
      key,
      status: key?.status ?? "none",
      isDefault: me?.default_provider === id,
      isActive: me?.active_provider === id,
    };
  });
}

/** Which provider the model stages use right now, and why, in one sentence. */
export function activeSummary(me: Pick<MeResponse, "default_provider" | "active_provider"> | undefined): { tone: "ok" | "warn"; text: string } | null {
  if (!me) return null;
  const active = providerName(me.active_provider);
  if (!me.active_provider) {
    return { tone: "warn", text: "No working key is saved, so chat, comparison, gap finding and directions are off until you add one." };
  }
  if (me.default_provider && me.default_provider !== me.active_provider) {
    return {
      tone: "warn",
      text: `Your default, ${providerName(me.default_provider)}, has no working key right now, so ${active} is used instead.`,
    };
  }
  return {
    tone: "ok",
    text: me.default_provider
      ? `Chat, comparison, gap finding and directions use ${active}, your default.`
      : `Chat, comparison, gap finding and directions use ${active}, the first working key you saved. Choose a default to decide.`,
  };
}

/** A key test's outcome in plain words (never the key itself). */
export function describeTest(result: LlmTestResult): string {
  if (!result.success) return result.message ? `It failed: ${result.message}.` : "It failed.";
  const parts: string[] = [];
  if (result.latency_ms != null) parts.push(`answered in ${result.latency_ms} ms`);
  const c = result.capabilities;
  if (c) {
    if (c.json_mode) parts.push("JSON mode");
    parts.push(`a ${c.context_tokens.toLocaleString("en-US")}-token context`);
    if (c.streaming) parts.push("streaming");
  }
  return parts.length ? `It works: ${parts.join(", ")}.` : "It works.";
}

/** Only the tail a saved key keeps; the key itself is never shown again. */
export const maskedKey = (last4: string) => `•••• ${last4}`;

export interface BudgetState {
  used: number;
  cap: number;
  fraction: number;
  reached: boolean;
  tokens: number;
}

/** A workspace's estimated spend against its cap (app/services/orchestrator/budget.py). */
export function budgetOf(ws: Pick<Workspace, "cost_used_usd" | "token_budget_usd" | "tokens_used">): BudgetState {
  const used = ws.cost_used_usd ?? 0;
  const cap = ws.token_budget_usd;
  return {
    used,
    cap,
    fraction: cap > 0 ? Math.min(1, used / cap) : 1,
    reached: used >= cap,
    tokens: (ws.tokens_used?.prompt ?? 0) + (ws.tokens_used?.completion ?? 0),
  };
}

export const usd = (v: number) => (v > 0 && v < 0.01 ? "<$0.01" : `$${v.toFixed(2)}`);

/** A cap the backend accepts: a positive amount, in cents. */
export function parseCap(input: string): number | null {
  const v = Number(input.trim().replace(/^\$/, ""));
  return Number.isFinite(v) && v > 0 ? Math.round(v * 100) / 100 : null;
}
