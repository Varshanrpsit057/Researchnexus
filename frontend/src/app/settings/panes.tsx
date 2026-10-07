"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR, { useSWRConfig } from "swr";
import { ArrowRight, Check, CheckCircle, CircleNotch, MinusCircle, WarningCircle, XCircle } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { papers as papersApi, service, usage, workspaces as workspacesApi } from "@/lib/api/endpoints";
import type { SourceCheck, SourceUse } from "@/lib/api/types";
import { DEFAULT_CRITERIA, criteriaError, criteriaName, sameCriteria, useSavedCriteria, writeCriteria } from "@/lib/ranking";
import { DEFAULT_PUBLISHERS, publishersPhrase, samePublishers, useSavedPublishers, writePublishers } from "@/lib/publishers";
import { RankingCriteriaControls } from "@/components/discovery/RankingCriteriaControls";
import { DeleteWorkspaceButton } from "@/components/workspaces/DeleteWorkspace";
import { C, InlineError, focusRing, panel, primaryButton, quietButton } from "@/components/cinematic/ui";
import { LoadFailure, SmallButton, WorkspaceRow } from "./parts";

type Announce = (text: string) => void;

// -- library & workspaces ---------------------------------------------------------

export function LibraryPane({ ready, announce }: { ready: boolean; announce: Announce }) {
  const { mutate } = useSWRConfig();
  const libraryQ = useSWR(ready ? "library" : null, () => papersApi.library());
  const workspacesQ = useSWR(ready ? "workspaces" : null, () => workspacesApi.list());
  const usageQ = useSWR(ready ? ["usage", "30d"] : null, () => usage.get("30d"));
  const [error, setError] = useState<string | null>(null);
  const counts = libraryQ.data?.counts;

  const facts: { term: string; value: number | undefined; hint: string }[] = [
    { term: "Papers in your library", value: counts?.papers, hint: "uploaded, analysed, searched from or collected" },
    { term: "With a research profile", value: counts?.analyzed, hint: "analysed, ready for discovery" },
    { term: "Discovery runs", value: counts?.discovery_runs, hint: "searches for related work you started" },
    { term: "Workspaces", value: workspacesQ.data?.workspaces.length, hint: "each with its trail, chat and synthesis" },
    { term: "Model calls, 30 days", value: usageQ.data?.totals.calls, hint: "with your own keys" },
  ];

  return (
    <>
      <dl className="overflow-hidden rounded-2xl" style={panel} data-testid="library-facts">
        {facts.map((f, i) => (
          <div key={f.term} className={`grid grid-cols-[4.5rem_minmax(0,1fr)] items-baseline gap-4 px-5 py-3 ${i > 0 ? "border-t" : ""}`} style={{ borderColor: C.line }}>
            <dt className="text-[14px]">
              {f.term}
              <span className="ml-2 text-[12.5px]" style={{ color: C.muted2 }}>
                {f.hint}
              </span>
            </dt>
            <dd className="order-first text-right text-[20px] font-bold tabular-nums leading-none">{f.value ?? "…"}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[13px]" style={{ color: C.muted }}>
        <Link href="/papers" className={`inline-flex items-center gap-1 rounded-sm font-semibold hover:text-white ${focusRing}`} style={{ color: C.mint }}>
          Open your library <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </p>

      <h3 className="mt-9 text-[16px] font-bold">Workspaces</h3>
      <p className="mt-1 text-[13.5px]" style={{ color: C.muted }}>
        Rename a workspace, or delete one you no longer need. Everything else lives inside the workspace.
      </p>
      {error && (
        <div className="mt-3">
          <InlineError message={error} />
        </div>
      )}
      <div className="mt-4">
        {workspacesQ.error ? (
          <LoadFailure what="your workspaces" onRetry={() => workspacesQ.mutate()} />
        ) : !workspacesQ.data ? (
          <div role="status" className="h-40 rounded-2xl motion-safe:animate-pulse" style={panel}>
            <span className="sr-only">Loading your workspaces…</span>
          </div>
        ) : workspacesQ.data.workspaces.length === 0 ? (
          <div className="rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <p className="text-sm" style={{ color: C.muted }}>
              No workspaces yet. A workspace starts from an analysed paper.
            </p>
            <Link href="/papers" className={`mt-4 inline-flex rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={{ ...quietButton, color: C.ink }}>
              Choose a paper
            </Link>
          </div>
        ) : (
          <ul className="divide-y divide-[rgba(150,175,230,0.12)] overflow-hidden rounded-2xl" style={panel} aria-label="Workspaces">
            {workspacesQ.data.workspaces.map((ws) => (
              <WorkspaceRow
                key={ws.workspace_id}
                ws={ws}
                onSaved={() => {
                  void workspacesQ.mutate();
                  void mutate(["workspace", ws.workspace_id]);
                }}
                extra={
                  <DeleteWorkspaceButton
                    ws={ws}
                    variant="text"
                    onDeleted={(t) => {
                      setError(null);
                      announce(`${t} deleted.`);
                      void libraryQ.mutate();
                    }}
                    onError={setError}
                  />
                }
              />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

// -- discovery defaults -------------------------------------------------------------

export function DiscoveryPane({ announce }: { announce: Announce }) {
  const saved = useSavedCriteria();
  const [draft, setDraft] = useState(saved);
  const preferred = useSavedPublishers();
  const publishersQ = useSWR("publishers", () => service.publishers());
  const invalid = criteriaError(draft);

  function changeCriteria(next: typeof draft) {
    setDraft(next);
    if (criteriaError(next) === null && writeCriteria(next)) announce("Ranking weights saved on this device.");
  }

  function togglePublisher(name: string) {
    const next = preferred.includes(name) ? preferred.filter((p) => p !== name) : [...preferred, name];
    announce(writePublishers(next) ? `Preferred publishers: ${publishersPhrase(next)}.` : "This browser blocks saving preferences.");
  }

  // the publishers worth offering: every one the server can name, and any the reader chose that it can't
  const known = publishersQ.data?.known ?? [...DEFAULT_PUBLISHERS];
  const choices = [...known, ...preferred.filter((p) => !known.includes(p))];

  return (
    <>
      <div className="rounded-2xl p-5" style={panel}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[16px] font-bold">Ranking weights</h3>
          <span className="text-[13px]" style={{ color: C.muted }}>
            Now: {criteriaName(saved)}
          </span>
        </div>
        <p className="mt-1 max-w-[68ch] text-[13.5px] leading-relaxed" style={{ color: C.muted }}>
          How much each criterion counts when the papers discovery finds are ranked. Only their proportions matter. A results page can still
          re-weigh its own run.
        </p>
        <div className="mt-5">
          <RankingCriteriaControls value={draft} onChange={changeCriteria} idPrefix="settings-criteria" columns={2} />
        </div>
        {invalid && (
          <div className="mt-3">
            <InlineError message={`${invalid} Not saved.`} />
          </div>
        )}
        {!sameCriteria(draft, DEFAULT_CRITERIA) && (
          <div className="mt-4">
            <SmallButton onClick={() => changeCriteria(DEFAULT_CRITERIA)}>Back to the default weights</SmallButton>
          </div>
        )}
      </div>

      <div className="mt-6 rounded-2xl p-5" style={panel}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[16px] font-bold">Preferred publishers</h3>
          <span className="text-[13px]" style={{ color: C.muted }}>
            {preferred.length} chosen
          </span>
        </div>
        <p className="mt-1 max-w-[68ch] text-[13.5px] leading-relaxed" style={{ color: C.muted }}>
          A paper from one of these scores on the <span style={{ color: C.ink }}>Preferred publisher</span> criterion, and the results&apos; publisher
          filter offers them together. A paper&apos;s publisher comes from Crossref or OpenAlex, else from its DOI.
        </p>
        <div role="group" aria-label="Preferred publishers" className="mt-4 flex flex-wrap gap-1.5">
          {choices.map((name) => {
            const on = preferred.includes(name);
            return (
              <button
                key={name}
                type="button"
                aria-pressed={on}
                onClick={() => togglePublisher(name)}
                className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors sm:min-h-9 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
                style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
              >
                {on && <Check className="size-3.5" weight="bold" aria-hidden />}
                {name}
              </button>
            );
          })}
        </div>
        <p className="mt-3 text-[13px]" style={{ color: preferred.length ? C.muted : C.warning }}>
          {preferred.length
            ? `Preferred: ${publishersPhrase(preferred)}.`
            : "No publisher is preferred, so the Preferred publisher criterion gives every paper the same score."}
        </p>
        {!samePublishers(preferred, DEFAULT_PUBLISHERS) && (
          <div className="mt-3">
            <SmallButton
              onClick={() =>
                announce(writePublishers(DEFAULT_PUBLISHERS) ? `Preferred publishers: ${publishersPhrase(DEFAULT_PUBLISHERS)}.` : "This browser blocks saving preferences.")
              }
            >
              Back to {publishersPhrase(DEFAULT_PUBLISHERS).replace(" or ", " and ")}
            </SmallButton>
          </div>
        )}
      </div>
      <p className="mt-4 text-[13px]" style={{ color: C.muted2 }}>
        Both are kept in this browser and used by every discovery you start from it.
      </p>
    </>
  );
}

// -- sources & full text ------------------------------------------------------------

const USE_LABEL: Record<SourceUse, string> = { discovery: "Discovery", records: "Paper records", full_text: "Full text" };

const CHECK_LOOK: Record<SourceCheck["status"], { label: string; color: string; Icon: typeof CheckCircle }> = {
  ok: { label: "Answered", color: C.mint, Icon: CheckCircle },
  limited: { label: "Limiting requests", color: C.warning, Icon: WarningCircle },
  refused: { label: "Refused", color: C.danger, Icon: XCircle },
  unreachable: { label: "Unreachable", color: C.danger, Icon: XCircle },
  error: { label: "Error", color: C.danger, Icon: XCircle },
  not_set_up: { label: "Not asked", color: C.muted, Icon: MinusCircle },
};

export function SourcesPane({ ready }: { ready: boolean }) {
  const sourcesQ = useSWR(ready ? "sources" : null, () => service.sources());
  const [checking, setChecking] = useState(false);
  const [checks, setChecks] = useState<Record<string, SourceCheck> | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);

  async function checkNow() {
    setChecking(true);
    setCheckError(null);
    try {
      const { results } = await service.checkSources();
      setChecks(Object.fromEntries(results.map((r) => [r.id, r])));
    } catch (err) {
      setCheckError(err instanceof ApiError ? `The check couldn't run: ${err.message}.` : "The check couldn't run: the server couldn't be reached.");
    } finally {
      setChecking(false);
    }
  }

  if (sourcesQ.error) return <LoadFailure what="the sources" onRetry={() => sourcesQ.mutate()} />;
  if (!sourcesQ.data) {
    return (
      <div role="status" className="h-72 rounded-2xl motion-safe:animate-pulse" style={panel}>
        <span className="sr-only">Loading the sources…</span>
      </div>
    );
  }
  const okCount = checks ? Object.values(checks).filter((c) => c.status === "ok").length : 0;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-[60ch] text-[13.5px] leading-relaxed" style={{ color: sourcesQ.data.contact_email_set ? C.muted : C.warning }}>
          {sourcesQ.data.contact_email_set
            ? "A contact email is set: Crossref and OpenAlex answer faster, and Unpaywall can be asked for open copies."
            : "No contact email is set, so Unpaywall isn't asked for open copies. Set RESEARCHNEXUS_CONTACT_EMAIL in backend/.env."}
        </p>
        <button
          type="button"
          onClick={checkNow}
          disabled={checking}
          className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition-opacity disabled:opacity-60 ${focusRing}`}
          style={primaryButton}
        >
          {checking && <CircleNotch className="size-4 motion-safe:animate-spin" aria-hidden />}
          {checking ? "Asking each source…" : checks ? "Check again" : "Check every source now"}
        </button>
      </div>
      <p className="sr-only" aria-live="polite">
        {checks ? `${okCount} of ${Object.keys(checks).length} sources answered.` : ""}
      </p>
      {checkError && (
        <div className="mt-3">
          <InlineError message={checkError} />
        </div>
      )}

      <div className="mt-4 overflow-x-auto rounded-2xl" style={panel}>
        <table className="w-full min-w-[720px] border-collapse text-left text-[13.5px]" data-testid="sources">
          <caption className="sr-only">The scholarly sources ResearchNexus reads</caption>
          <thead>
            <tr className="border-b text-[12.5px]" style={{ borderColor: C.lineStrong, color: C.muted }}>
              <th scope="col" className="px-5 py-3 font-semibold">
                Source
              </th>
              <th scope="col" className="px-4 py-3 font-semibold">
                Used for
              </th>
              <th scope="col" className="px-4 py-3 font-semibold">
                Access
              </th>
              <th scope="col" className="px-5 py-3 font-semibold">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {sourcesQ.data.sources.map((s) => {
              const check = checks?.[s.id];
              const look = check ? CHECK_LOOK[check.status] : null;
              return (
                <tr key={s.id} className="border-b align-top last:border-b-0" style={{ borderColor: C.line }}>
                  <th scope="row" className="px-5 py-3.5 text-left font-semibold">
                    {s.name}
                  </th>
                  <td className="px-4 py-3.5" style={{ color: C.muted }}>
                    {s.used_for.map((u) => USE_LABEL[u]).join(" · ")}
                  </td>
                  <td className="px-4 py-3.5">
                    {s.key === "configured" ? (
                      <span style={{ color: C.mint }}>Your key</span>
                    ) : (
                      <span style={{ color: C.muted }}>
                        {s.key === "not_set" ? `No key: ${s.keyless.charAt(0).toLowerCase()}${s.keyless.slice(1)}` : s.keyless}
                      </span>
                    )}
                    {s.key === "not_set" && s.key_setting && (
                      <span className="mt-0.5 block font-mono text-[11.5px]" style={{ color: C.muted2 }}>
                        {s.key_setting}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5">
                    {checking ? (
                      <span style={{ color: C.muted2 }}>Asking…</span>
                    ) : look && check ? (
                      <span className="inline-flex items-start gap-1.5" style={{ color: look.color }}>
                        <look.Icon className="mt-0.5 size-4 shrink-0" weight="fill" aria-hidden />
                        <span>
                          {look.label}
                          {check.latency_ms != null && check.status === "ok" && (
                            <span className="whitespace-nowrap tabular-nums" style={{ color: C.muted }}>
                              {" "}
                              in {check.latency_ms < 1000 ? `${check.latency_ms} ms` : `${(check.latency_ms / 1000).toFixed(1)} s`}
                            </span>
                          )}
                          {check.detail && check.status !== "ok" && (
                            <span className="block max-w-[32ch] text-[12.5px]" style={{ color: C.muted }}>
                              {check.detail}
                            </span>
                          )}
                        </span>
                      </span>
                    ) : (
                      <span style={{ color: C.muted2 }}>{s.available ? "Not checked yet" : "Not asked: needs a contact email"}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-4 max-w-[78ch] text-[13px] leading-relaxed" style={{ color: C.muted2 }}>
        Every source works without a key. A key goes in <span className="font-mono">backend/.env</span> under the name shown, and applies after the
        server restarts. Keys are sent only to their own source and are never shown here. Checking asks each source one question, so it uses one
        request of each one&apos;s allowance.
      </p>
    </>
  );
}
