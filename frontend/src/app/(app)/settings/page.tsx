"use client";

import { useState, type FormEvent } from "react";
import useSWR from "swr";
import { CheckCircle, Trash, WarningCircle, XCircle } from "@phosphor-icons/react/dist/ssr";
import { llmKeys } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { LlmProvider } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";
import { TextInput } from "@/components/ui/Field";
import { InlineError, Skeleton } from "@/components/ui/States";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";

const PROVIDERS: { value: LlmProvider; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "groq", label: "Groq" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "together", label: "Together" },
  { value: "gemini", label: "Gemini" },
];

export default function SettingsPage() {
  const { data, isLoading, mutate } = useSWR("llm-keys", () => llmKeys.list());
  const [provider, setProvider] = useState<LlmProvider>("groq");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await llmKeys.save(provider, apiKey);
      setApiKey("");
      await mutate();
    } catch (err) {
      // No ApiError means no readable response at all: the server is down, or it
      // crashed (a crash answers without CORS headers). The key isn't the problem.
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't reach the server to save this key. Check that the backend is running, then try again."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(p: LlmProvider) {
    await llmKeys.remove(p);
    await mutate();
  }

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6 border-b border-border-strong pb-4">
        <h1 className="text-xl font-semibold tracking-tightest text-ink">LLM provider keys</h1>
        <p className="mt-1 text-sm text-ink-muted">
          ResearchNexus is bring-your-own-key: every profile extraction, discovery, chat, gap, and direction call runs on your
          own provider account. Your key is encrypted at rest and never sent back to this browser after saving.
        </p>
      </div>

      <Card className="mb-6">
        <CardHeader>
          <h2 className="text-sm font-semibold text-ink">Add or update a key</h2>
        </CardHeader>
        <CardBody>
          <form onSubmit={handleSave} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="provider" className="text-sm font-medium text-ink">
                Provider
              </label>
              <select
                id="provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value as LlmProvider)}
                className="h-10 rounded-sm border border-border-strong bg-surface-raised px-3 text-sm text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <TextInput
              label="API key"
              type="password"
              autoComplete="off"
              required
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
            {error && <InlineError message={error} />}
            <Button type="submit" loading={saving} className="self-start">
              Save key
            </Button>
          </form>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-ink">Saved keys</h2>
        </CardHeader>
        <CardBody>
          {isLoading && (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          )}
          {!isLoading && data?.keys.length === 0 && (
            <p className="text-sm text-ink-muted">No keys saved yet. Add one above to unlock generative features.</p>
          )}
          {!isLoading && data && data.keys.length > 0 && (
            <ul className="flex flex-col divide-y divide-border">
              {data.keys.map((key) => (
                <li key={key.provider} className="flex items-center justify-between py-2.5">
                  <div className="flex items-center gap-2.5">
                    <StatusIcon status={key.status} />
                    <div>
                      <p className="text-sm font-medium capitalize text-ink">{key.provider}</p>
                      <p className="font-mono text-xs text-ink-subtle">•••• {key.key_last4}</p>
                    </div>
                    <span className="font-mono text-[0.6875rem] uppercase tracking-wider text-ink-subtle">{key.status}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRemove(key.provider)}
                    aria-label={`Remove ${key.provider} key`}
                    className="rounded-sm p-2 text-ink-muted hover:bg-danger-wash hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
                  >
                    <Trash className="size-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "working") return <CheckCircle className="size-5 text-verified" weight="fill" aria-hidden />;
  if (status === "failed") return <XCircle className="size-5 text-danger" weight="fill" aria-hidden />;
  return <WarningCircle className="size-5 text-warning" weight="fill" aria-hidden />;
}
