"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type ComponentType, type ReactNode } from "react";
import useSWR, { useSWRConfig } from "swr";
import {
  Books,
  ChartBar,
  Globe,
  Info,
  Key,
  PaintBrush,
  SlidersHorizontal,
  UserCircle,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import { apiBase, ApiError } from "@/lib/api/client";
import { auth as authApi, llmKeys, service } from "@/lib/api/endpoints";
import type { CitationFormat, LlmProvider } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { STYLE_LABEL } from "@/lib/citations";
import { usePreference, writePreference, type Preferences } from "@/lib/preferences";
import { useBackground, useBackgroundChoice, writeBackgroundChoice, type BackgroundChoice } from "@/lib/background-mode";
import { activeSummary, describeTest, providerName, providerRows } from "@/lib/settings";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { C, focusRing, panel, quietButton } from "@/components/cinematic/ui";
import { KeyForm, LoadFailure, ProviderLine, SmallButton } from "./parts";
import { AccountPane } from "./account";
import { DiscoveryPane, LibraryPane, SourcesPane } from "./panes";
import { UsagePanel } from "./usage";

type SectionId = "account" | "library" | "discovery" | "sources" | "models" | "usage" | "appearance" | "service";

const SECTIONS: { id: SectionId; label: string; title: string; lead: string; icon: ComponentType<{ className?: string; "aria-hidden"?: boolean; weight?: "regular" | "fill" }> }[][] = [
  [
    { id: "account", label: "Account", title: "Account", lead: "Your profile, your password, and the devices signed in to your account.", icon: UserCircle },
    {
      id: "library",
      label: "Library & workspaces",
      title: "Library & workspaces",
      lead: "What you have built up here, and your workspaces: rename one, or delete one you no longer need.",
      icon: Books,
    },
  ],
  [
    {
      id: "discovery",
      label: "Discovery defaults",
      title: "Discovery defaults",
      lead: "How the papers discovery finds are ranked, and which publishers you prefer.",
      icon: SlidersHorizontal,
    },
    {
      id: "sources",
      label: "Sources & full text",
      title: "Sources & full text",
      lead: "The scholarly sources discovery searches, paper records are completed from and full text is fetched from, and how each is doing.",
      icon: Globe,
    },
  ],
  [
    {
      id: "models",
      label: "Language models",
      title: "Language models",
      lead: "ResearchNexus calls a language model with your own key for analysis, chat, comparison, gap finding and directions. Discovery, ranking and references never need one.",
      icon: Key,
    },
    {
      id: "usage",
      label: "Model usage",
      title: "Model usage",
      lead: "What your keys have used, in tokens, as each provider counted them: every call, including ones that failed or whose answer was never saved.",
      icon: ChartBar,
    },
  ],
  [
    { id: "appearance", label: "Appearance", title: "Appearance", lead: "How the app looks in this browser. Saved here only, and applied at once.", icon: PaintBrush },
    { id: "service", label: "Service & about", title: "Service & about", lead: "The ResearchNexus server this app talks to.", icon: Info },
  ],
];
const ALL = SECTIONS.flat();
const isSection = (v: string): v is SectionId => ALL.some((s) => s.id === v);

// the open section is the URL's hash (#models), so old links and the back button work
const HASH_EVENT = "researchnexus:settings-section";
function subscribeHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  window.addEventListener(HASH_EVENT, onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
    window.removeEventListener(HASH_EVENT, onChange);
  };
}
const readHash = () => window.location.hash.slice(1);

const reducedMotion = () => (typeof window !== "undefined" ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : false);
const subscribeMotion = (onChange: () => void) => {
  const m = window.matchMedia("(prefers-reduced-motion: reduce)");
  m.addEventListener("change", onChange);
  return () => m.removeEventListener("change", onChange);
};

export default function SettingsPage() {
  const { ready } = useRequireAuth();
  const { me, refreshMe } = useAuth();
  const hash = useSyncExternalStore(subscribeHash, readHash, () => "");
  const section: SectionId = isSection(hash) ? hash : "account";
  const current = ALL.find((s) => s.id === section)!;
  const [announcement, setAnnouncement] = useState("");

  // the account as the server has it now: keys can change from another tab or device
  const refreshedOnOpen = useRef(false);
  useEffect(() => {
    if (ready && !refreshedOnOpen.current) {
      refreshedOnOpen.current = true;
      refreshMe();
    }
  }, [ready, refreshMe]);

  function open(id: SectionId) {
    window.history.replaceState(null, "", `#${id}`);
    window.dispatchEvent(new Event(HASH_EVENT));
    setAnnouncement(`${ALL.find((s) => s.id === id)?.title ?? ""} settings.`);
  }

  if (!ready) return null;

  const modelsHint = me ? (me.active_provider ? providerName(me.active_provider) : "No key") : null;

  return (
    <PageShell>
      <header className="border-b pb-6" style={{ borderColor: C.lineStrong }}>
        <h1 className="text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Settings</h1>
        <p className="mt-3 max-w-[68ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
          Your account and library, how discovery ranks what it finds, the sources it reads, the language models used on your behalf, and how
          the app looks.
        </p>
      </header>

      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>

      {/* minmax(0,1fr): the column never grows past the window. The sidebar
          from 768 px; narrower, the sections wrap, so none is out of sight. */}
      <div className="mt-8 grid grid-cols-[minmax(0,1fr)] gap-8 md:grid-cols-[208px_minmax(0,1fr)] md:gap-10 lg:grid-cols-[232px_minmax(0,1fr)] lg:gap-12">
        <nav aria-label="Settings sections" className="min-w-0 md:sticky md:top-6 md:self-start">
          <ul className="flex flex-wrap gap-1.5 md:flex-col md:flex-nowrap md:gap-0">
            {SECTIONS.map((group, g) =>
              group.map((s, i) => {
                const on = s.id === section;
                const Icon = s.icon;
                return (
                  <li key={s.id} className={g > 0 && i === 0 ? "md:mt-3 md:border-t md:pt-3" : ""} style={{ borderColor: C.line }}>
                    <a
                      href={`#${s.id}`}
                      onClick={(e) => {
                        e.preventDefault();
                        open(s.id);
                      }}
                      aria-current={on ? "page" : undefined}
                      className={`flex min-h-11 items-center gap-2.5 whitespace-nowrap rounded-xl px-3 text-[14px] transition-colors md:min-h-10 ${on ? "" : "hover:bg-white/[0.05] hover:text-white"} ${focusRing}`}
                      style={
                        on
                          ? { background: "rgba(93,240,168,.09)", color: C.ink, border: "1px solid rgba(93,240,168,.22)" }
                          : { color: C.muted, border: "1px solid transparent" }
                      }
                    >
                      <Icon className="size-[18px] shrink-0" weight={on ? "fill" : "regular"} aria-hidden />
                      <span className={on ? "font-semibold" : ""}>{s.label}</span>
                      {s.id === "models" && modelsHint && (
                        <span className="ml-auto hidden text-[12px] lg:inline" style={{ color: me?.active_provider ? C.muted2 : C.warning }}>
                          {modelsHint}
                        </span>
                      )}
                    </a>
                  </li>
                );
              }),
            )}
          </ul>
        </nav>

        <section id={section} aria-labelledby="settings-pane-title" className="min-w-0" key={section}>
          <h2 id="settings-pane-title" className="text-[22px] font-bold tracking-[-0.015em]">
            {current.title}
          </h2>
          <p className="mt-1.5 max-w-[70ch] text-[14px] leading-relaxed" style={{ color: C.muted }}>
            {current.lead}
          </p>
          <div className="mt-6">
            {section === "account" && <AccountPane onAddKey={() => open("models")} announce={setAnnouncement} />}
            {section === "library" && <LibraryPane ready={ready} announce={setAnnouncement} />}
            {section === "discovery" && <DiscoveryPane announce={setAnnouncement} />}
            {section === "sources" && <SourcesPane ready={ready} />}
            {section === "models" && <ModelsPane />}
            {section === "usage" && <UsagePanel ready={ready} />}
            {section === "appearance" && <AppearancePane announce={setAnnouncement} />}
            {section === "service" && <ServicePane ready={ready} />}
          </div>
        </section>
      </div>
    </PageShell>
  );
}

// -- language models ------------------------------------------------------------------

function ModelsPane() {
  const { me, refreshMe } = useAuth();
  const { mutate } = useSWRConfig();
  const keysQ = useSWR("llm-keys", () => llmKeys.list());
  const [formProvider, setFormProvider] = useState<LlmProvider>("groq");
  const [busyProvider, setBusyProvider] = useState<LlmProvider | null>(null);
  const [notes, setNotes] = useState<Partial<Record<LlmProvider, { ok: boolean; text: string }>>>({});
  const keyInput = useRef<HTMLInputElement>(null);
  const systemReduced = useSyncExternalStore(subscribeMotion, reducedMotion, () => false);
  const rows = providerRows(keysQ.data?.keys ?? [], me);
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

  return (
    <>
      {summary && (
        <p
          className="mb-4 flex items-start gap-2 rounded-xl px-4 py-3 text-[14px] leading-snug"
          style={
            summary.tone === "ok"
              ? { background: "rgba(93,240,168,.07)", border: "1px solid rgba(93,240,168,.3)" }
              : { background: "rgba(232,193,92,.07)", border: "1px solid rgba(232,193,92,.35)", color: C.warning }
          }
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
    </>
  );
}

// -- appearance -----------------------------------------------------------------------

function AppearancePane({ announce }: { announce: (text: string) => void }) {
  const background = useBackground();
  const backgroundChoice = useBackgroundChoice();
  const referenceStyle = usePreference("referenceStyle");
  const systemReduced = useSyncExternalStore(subscribeMotion, reducedMotion, () => false);

  function setPref<K extends keyof Preferences>(key: K, value: Preferences[K], label: string) {
    announce(writePreference(key, value) ? `${label} saved on this device.` : "This browser blocks saving preferences.");
  }

  return (
    <div className="space-y-6 rounded-2xl p-5" style={panel}>
      <Choice
        label="Background"
        hint={[
          "Auto picks by the graphics this browser uses: the neural network with a dedicated GPU, the fibers without one, and the fibers at a lighter setting where the GPU is weak (drawn in software). Only a browser without WebGL gets a still background.",
          background ? `${background.reason}${background.renderer ? ` Graphics in use: ${rendererName(background.renderer)}.` : ""}` : "",
          systemReduced ? "Your system asks for reduced motion, so any animation stays still." : "",
        ]
          .filter(Boolean)
          .join(" ")}
        options={[
          { value: "auto", label: "Auto" },
          { value: "animated", label: "Neural network" },
          { value: "fibers", label: "Fibers" },
          { value: "static", label: "Static" },
        ]}
        value={backgroundChoice}
        onChange={(v) => announce(writeBackgroundChoice(v as BackgroundChoice) ? "Background saved on this device." : "This browser blocks saving preferences.")}
      />
      <div className="border-t" style={{ borderColor: C.line }} />
      <Choice
        label="Reference style"
        hint="The style the citations page opens in; you can still switch there."
        options={(Object.keys(STYLE_LABEL) as CitationFormat[]).map((s) => ({ value: s, label: STYLE_LABEL[s] }))}
        value={referenceStyle}
        onChange={(v) => setPref("referenceStyle", v as CitationFormat, "Reference style")}
      />
    </div>
  );
}

// -- service & about ------------------------------------------------------------------

function ServicePane({ ready }: { ready: boolean }) {
  const healthQ = useSWR(ready ? "service-health" : null, () => service.health(), { refreshInterval: 30_000 });
  return (
    <>
      <div className="rounded-2xl p-5" style={panel} data-testid="service-status">
        {healthQ.error ? (
          <>
            <p className="flex items-start gap-2 text-[14px]" style={{ color: C.danger }}>
              <Warning className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden />
              {/localhost|127\.0\.0\.1/.test(apiBase())
                ? `Can't reach the server at ${apiBase()}. Start the backend on port 8000 (python start.py), then try again.`
                : "The server isn't answering right now. Try again in a minute."}
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
          <dl className="grid grid-cols-[minmax(0,1fr)] gap-5 sm:grid-cols-3">
            <Field term="Server">
              <span className="font-mono text-[13px] [overflow-wrap:anywhere]">{apiBase()}</span>
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
      <div className="mt-6 max-w-[72ch] space-y-3 text-[14px] leading-relaxed" style={{ color: C.muted }}>
        <h3 className="text-[16px] font-bold" style={{ color: C.ink }}>
          About ResearchNexus
        </h3>
        <p>
          ResearchNexus takes one seed paper through a research profile, a search of the scholarly sources for related work, a ranking you can
          weigh and inspect, a typed research trail, and a workspace with chat, comparison, gaps and directions.
        </p>
        <p>
          Every claim it shows points to the passage it rests on, every reference is formatted from the paper&apos;s record, and every score is
          the one it computed. When it can&apos;t find support, it says so instead of guessing.
        </p>
      </div>
    </>
  );
}

// -- small parts ---------------------------------------------------------------------

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

/** "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Ti (0x00002803) Direct3D11 ...)" -> "NVIDIA GeForce RTX 4060 Ti" */
function rendererName(renderer: string): string {
  const angle = /^ANGLE \([^,]+, (.+?)(?: \(0x[0-9a-f]+\))?(?: Direct3D| OpenGL| Vulkan| Metal|,)/i.exec(renderer);
  return (angle?.[1] ?? renderer).trim();
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
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-[160px_minmax(0,1fr)] sm:items-start">
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
