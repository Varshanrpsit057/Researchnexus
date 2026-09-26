"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import Link from "next/link";
import useSWR, { useSWRConfig } from "swr";
import { Copy, SignOut, Warning } from "@phosphor-icons/react/dist/ssr";
import { API_BASE_URL, ApiError } from "@/lib/api/client";
import { auth as authApi, llmKeys, service, workspaces as workspacesApi } from "@/lib/api/endpoints";
import type { CitationFormat, LlmProvider } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { STYLE_LABEL } from "@/lib/citations";
import { usePreference, writePreference, type Preferences } from "@/lib/preferences";
import { activeSummary, describeTest, providerName, providerRows } from "@/lib/settings";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { C, focusRing, panel, quietButton } from "../workspace/[id]/ui";
import { KeyForm, LoadFailure, ProviderLine, Section, SmallButton, WorkspaceBudget } from "./parts";

const SECTIONS = [
  { id: "account", label: "Account" },
  { id: "models", label: "Language models" },
  { id: "workspaces", label: "Workspaces" },
  { id: "device", label: "This device" },
  { id: "service", label: "Service" },
];

const reducedMotion = () => (typeof window !== "undefined" ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : false);
const subscribeMotion = (onChange: () => void) => {
  const m = window.matchMedia("(prefers-reduced-motion: reduce)");
  m.addEventListener("change", onChange);
  return () => m.removeEventListener("change", onChange);
};

export default function SettingsPage() {
  const { ready } = useRequireAuth();
  const { me, signOut, refreshMe } = useAuth();
  const { mutate } = useSWRConfig();
  const keysQ = useSWR(ready ? "llm-keys" : null, () => llmKeys.list());
  const workspacesQ = useSWR(ready ? "workspaces" : null, () => workspacesApi.list());
  const healthQ = useSWR(ready ? "service-health" : null, () => service.health(), { refreshInterval: 30_000 });

  const [formProvider, setFormProvider] = useState<LlmProvider>("groq");
  const [busyProvider, setBusyProvider] = useState<LlmProvider | null>(null);
  const [notes, setNotes] = useState<Partial<Record<LlmProvider, { ok: boolean; text: string }>>>({});
  const [announcement, setAnnouncement] = useState("");
  const keyInput = useRef<HTMLInputElement>(null);
  const motion = usePreference("backgroundMotion");
  const referenceStyle = usePreference("referenceStyle");
  const systemReduced = useSyncExternalStore(subscribeMotion, reducedMotion, () => false);

  // the account as the server has it now: keys can change from another tab or device
  const refreshedOnOpen = useRef(false);
  useEffect(() => {
    if (ready && !refreshedOnOpen.current) {
      refreshedOnOpen.current = true;
      refreshMe();
    }
  }, [ready, refreshMe]);

  const keys = keysQ.data?.keys ?? [];
  const rows = providerRows(keys, me);
  const summary = activeSummary(me);

  function refreshAccount() {
    void keysQ.mutate();
    refreshMe();
  }

  async function withProvider(p: LlmProvider, run: () => Promise<{ ok: boolean; text: string }>) {
    setBusyProvider(p);
    try {
      const note = await run(); // shown in the provider's own role="status" line
      setNotes((n) => ({ ...n, [p]: note }));
    } catch (e) {
      const text = e instanceof ApiError ? e.message : "Couldn't reach the server; nothing changed.";
      setNotes((n) => ({ ...n, [p]: { ok: false, text } }));
    } finally {
      setBusyProvider(null);
    }
  }

  const setDefault = (p: LlmProvider, isDefault: boolean) =>
    withProvider(p, async () => {
      const next = await authApi.updateMe({ default_provider: isDefault ? null : p });
      await mutate("me", next, { revalidate: false });
      return {
        ok: true,
        text: isDefault ? `${providerName(p)} is no longer the default.` : `${providerName(p)} is now the default for every model stage.`,
      };
    });

  const check = (p: LlmProvider) =>
    withProvider(p, async () => {
      const { result } = await llmKeys.check(p);
      refreshAccount();
      return { ok: result.success, text: `Checked just now. ${describeTest(result)}` };
    });

  const remove = (p: LlmProvider) =>
    withProvider(p, async () => {
      await llmKeys.remove(p);
      refreshAccount();
      return { ok: true, text: `The ${providerName(p)} key is removed from this server.` };
    });

  function replace(p: LlmProvider) {
    setFormProvider(p);
    requestAnimationFrame(() => {
      keyInput.current?.focus();
      keyInput.current?.scrollIntoView({ block: "center", behavior: systemReduced ? "auto" : "smooth" });
    });
  }

  function setPref<K extends keyof Preferences>(key: K, value: Preferences[K], label: string) {
    setAnnouncement(writePreference(key, value) ? `${label} saved on this device.` : "This browser blocks saving preferences.");
  }

  async function copyId() {
    if (!me) return;
    try {
      await navigator.clipboard.writeText(me.id);
      setAnnouncement("Account ID copied.");
    } catch {
      setAnnouncement("Couldn't copy; select the ID instead.");
    }
  }

  if (!ready) return null;

  return (
    <PageShell>
      <div className="selection:bg-[rgba(93,240,168,0.28)] selection:text-white">
        <header className="border-b pb-6" style={{ borderColor: C.lineStrong }}>
          <h1 className="text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Settings</h1>
          <p className="mt-3 max-w-[68ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
            Your account, the language model keys ResearchNexus uses on your behalf, each workspace&apos;s spending cap, and how the app looks on this device.
          </p>
        </header>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>

        <div className="mt-8 grid gap-10 lg:grid-cols-[200px_minmax(0,1fr)]">
          <nav aria-label="Settings sections" className="lg:sticky lg:top-24 lg:self-start">
            <ul className="flex flex-wrap gap-x-5 gap-y-1 lg:flex-col lg:gap-1">
              {SECTIONS.map((s) => (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    className={`inline-flex min-h-11 items-center rounded-sm text-[14px] hover:text-white lg:min-h-9 ${focusRing}`}
                    style={{ color: C.muted }}
                  >
                    {s.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <div className="min-w-0 space-y-10">
            {/* account */}
            <Section id="account" title="Account" lead="Who is signed in to this ResearchNexus server.">
              {!me ? (
                <div role="status" className="h-28 rounded-2xl motion-safe:animate-pulse" style={panel}>
                  <span className="sr-only">Loading your account…</span>
                </div>
              ) : (
                <div className="rounded-2xl p-5" style={panel}>
                  <dl className="grid gap-4 sm:grid-cols-2">
                    <Field term="Email">
                      <span className="text-[16px] font-semibold [overflow-wrap:anywhere]">{me.email}</span>
                    </Field>
                    <Field term="Member since">
                      {new Date(me.created_at).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}
                    </Field>
                    <Field term="Account ID">
                      <span className="inline-flex items-center gap-2">
                        <span className="font-mono text-[13px] [overflow-wrap:anywhere]" style={{ color: C.muted }}>
                          {me.id}
                        </span>
                        <button
                          type="button"
                          onClick={copyId}
                          aria-label="Copy the account ID"
                          className={`inline-flex size-11 items-center justify-center rounded-lg hover:bg-white/10 sm:size-8 ${focusRing}`}
                          style={{ color: C.muted }}
                        >
                          <Copy className="size-4" aria-hidden />
                        </button>
                      </span>
                    </Field>
                    <Field term="Sign-in">
                      <span style={{ color: C.muted }}>Local sign-in: the email is the account. There is no password to change.</span>
                    </Field>
                  </dl>
                  <div className="mt-5 border-t pt-4" style={{ borderColor: C.line }}>
                    <button
                      type="button"
                      onClick={signOut}
                      className={`inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-sm font-semibold transition-colors hover:bg-white/10 sm:min-h-9 ${focusRing}`}
                      style={{ ...quietButton, color: C.ink }}
                    >
                      <SignOut className="size-4" aria-hidden />
                      Sign out
                    </button>
                  </div>
                </div>
              )}
            </Section>

            {/* models */}
            <Section
              id="models"
              title="Language models"
              lead="ResearchNexus calls a language model with your own key for chat, comparison, gap finding and directions. Discovery, ranking and references never need one."
            >
              {summary && (
                <p
                  className="mb-4 flex items-start gap-2 rounded-xl px-4 py-3 text-[14px] leading-snug"
                  style={summary.tone === "ok" ? { background: "rgba(93,240,168,.07)", border: "1px solid rgba(93,240,168,.3)" } : { background: "rgba(232,193,92,.07)", border: "1px solid rgba(232,193,92,.35)", color: C.warning }}
                  data-testid="model-status"
                >
                  {summary.tone === "warn" && <Warning className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden />}
                  {summary.text}
                </p>
              )}
              {keysQ.error ? (
                <LoadFailure what="your keys" onRetry={() => keysQ.mutate()} />
              ) : !keysQ.data ? (
                <div role="status" className="h-64 rounded-2xl motion-safe:animate-pulse" style={panel}>
                  <span className="sr-only">Loading your keys…</span>
                </div>
              ) : (
                <ul className="divide-y divide-[rgba(150,175,230,0.12)] overflow-hidden rounded-2xl" style={{ ...panel, borderColor: C.line }} aria-label="Providers">
                  {rows.map((row) => (
                    <ProviderLine
                      key={row.id}
                      row={row}
                      busy={busyProvider === row.id}
                      note={notes[row.id] ?? null}
                      onDefault={() => setDefault(row.id, row.isDefault)}
                      onCheck={() => check(row.id)}
                      onReplace={() => replace(row.id)}
                      onRemove={() => remove(row.id)}
                    />
                  ))}
                </ul>
              )}
              <div className="mt-5">
                <KeyForm provider={formProvider} onProvider={setFormProvider} inputRef={keyInput} onSaved={refreshAccount} />
              </div>
            </Section>

            {/* workspaces */}
            <Section
              id="workspaces"
              title="Workspaces"
              lead="Each workspace has a cap on its estimated model spend. Near the cap it works lighter; at the cap its model stages pause until you raise it. The estimate uses a flat rate: your provider bills you, not ResearchNexus."
            >
              {workspacesQ.error ? (
                <LoadFailure what="your workspaces" onRetry={() => workspacesQ.mutate()} />
              ) : !workspacesQ.data ? (
                <div role="status" className="h-40 rounded-2xl motion-safe:animate-pulse" style={panel}>
                  <span className="sr-only">Loading your workspaces…</span>
                </div>
              ) : workspacesQ.data.workspaces.length === 0 ? (
                <div className="rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                  <p className="text-sm" style={{ color: C.muted }}>
                    No workspaces yet. A workspace starts from a seed paper.
                  </p>
                  <Link href="/papers" className={`mt-4 inline-flex rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={{ ...quietButton, color: C.ink }}>
                    Upload a paper
                  </Link>
                </div>
              ) : (
                <ul className="divide-y divide-[rgba(150,175,230,0.12)] overflow-hidden rounded-2xl" style={{ ...panel, borderColor: C.line }} aria-label="Workspaces">
                  {workspacesQ.data.workspaces.map((ws) => (
                    <WorkspaceBudget
                      key={ws.workspace_id}
                      ws={ws}
                      onSaved={() => {
                        void workspacesQ.mutate();
                        void mutate(["workspace", ws.workspace_id]);
                      }}
                    />
                  ))}
                </ul>
              )}
            </Section>

            {/* this device */}
            <Section id="device" title="This device" lead="Saved in this browser only, and applied at once.">
              <div className="space-y-5 rounded-2xl p-5" style={panel}>
                <Choice
                  label="Background"
                  hint={
                    systemReduced
                      ? "Your system asks for reduced motion, so the background stays still either way."
                      : "The neural background moves gently; a still frame is lighter on slow machines and easier on the eyes."
                  }
                  options={[
                    { value: "moving", label: "Moving" },
                    { value: "still", label: "Still" },
                  ]}
                  value={motion}
                  onChange={(v) => setPref("backgroundMotion", v as Preferences["backgroundMotion"], "Background")}
                />
                <Choice
                  label="Reference style"
                  hint="The style the citations page opens in; you can still switch there."
                  options={(Object.keys(STYLE_LABEL) as CitationFormat[]).map((s) => ({ value: s, label: STYLE_LABEL[s] }))}
                  value={referenceStyle}
                  onChange={(v) => setPref("referenceStyle", v as CitationFormat, "Reference style")}
                />
              </div>
            </Section>

            {/* service */}
            <Section id="service" title="Service" lead="The ResearchNexus server this app talks to.">
              <div className="rounded-2xl p-5" style={panel} data-testid="service-status">
                {healthQ.error ? (
                  <>
                    <p className="flex items-start gap-2 text-[14px]" style={{ color: C.danger }}>
                      <Warning className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden />
                      Can&apos;t reach the server at {API_BASE_URL}. Start the backend on port 8000, then try again.
                    </p>
                    <div className="mt-3">
                      <SmallButton onClick={() => healthQ.mutate()}>Try again</SmallButton>
                    </div>
                  </>
                ) : !healthQ.data ? (
                  <p role="status" className="text-[14px]" style={{ color: C.muted }}>
                    Checking the server…
                  </p>
                ) : (
                  <dl className="grid gap-4 sm:grid-cols-3">
                    <Field term="Server">
                      <span className="font-mono text-[13px]">{API_BASE_URL}</span>
                    </Field>
                    <Field term="Status">
                      <span style={{ color: healthQ.data.status === "ok" ? C.mint : C.warning }}>
                        {healthQ.data.status === "ok" ? "Connected" : "Degraded"} · database {healthQ.data.checks.db ?? "unknown"}
                      </span>
                    </Field>
                    <Field term="Version">
                      <span className="tabular-nums">{healthQ.data.version}</span>
                    </Field>
                  </dl>
                )}
              </div>
            </Section>
          </div>
        </div>
      </div>
    </PageShell>
  );
}

function Field({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
        {term}
      </dt>
      <dd className="mt-1 text-[14.5px]">{children}</dd>
    </div>
  );
}

function Choice({
  label,
  hint,
  options,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-[160px_minmax(0,1fr)] sm:items-start">
      <p className="text-[14px] font-semibold sm:pt-2">{label}</p>
      <div>
        <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
          {options.map((o) => {
            const on = o.value === value;
            return (
              <button
                key={o.value}
                type="button"
                aria-pressed={on}
                onClick={() => onChange(o.value)}
                className={`min-h-11 rounded-full px-4 text-[13px] font-medium transition-colors sm:min-h-9 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
                style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
              >
                {o.label}
              </button>
            );
          })}
        </div>
        <p className="mt-1.5 text-[13px] leading-snug" style={{ color: C.muted }}>
          {hint}
        </p>
      </div>
    </div>
  );
}
