"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { ArrowLeft, MagnifyingGlass } from "@phosphor-icons/react/dist/ssr";
import { papers as papersApi, workspaces } from "@/lib/api/endpoints";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import type { Confidence, EdgeUserState, GroupedTrail, RelationshipType } from "@/lib/api/types";
import { RELATIONSHIP_TYPES } from "@/lib/api/types";
import { RELATIONSHIP_COPY, countByState, filterTrail, flattenTrail, type TrailEntry } from "@/lib/trail";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { C, InlineError, WorkspaceLoadError, focusRing, panel, primaryButton, quietButton } from "../ui";
import { TrailRow, type Seed } from "./TrailRow";

const TABS: { state: EdgeUserState; label: string; empty: string }[] = [
  { state: "pending", label: "To review", empty: "Nothing is waiting for review." },
  { state: "accepted", label: "Accepted", empty: "No connections accepted yet." },
  { state: "rejected", label: "Rejected", empty: "No connections rejected." },
];

const DONE_TEXT: Record<EdgeUserState, string> = {
  accepted: "Accepted",
  rejected: "Rejected",
  pending: "Moved back to review",
};

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`motion-safe:animate-pulse rounded-2xl ${className}`} style={panel} />;
}

export default function TrailPage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const { mutate: mutateGlobal } = useSWRConfig();
  // ?edge=<id>: arrive at one connection (from the research graph)
  const linkedEdge = useSearchParams().get("edge");

  const workspaceQ = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));
  const trailKey = ["ws-trail-all", id];
  const trailQ = useSWR(ready && workspaceQ.data ? trailKey : null, () => workspaces.trail(id, { state: "all" }));

  const [tab, setTab] = useState<EdgeUserState | null>(null);
  const [types, setTypes] = useState<Set<RelationshipType>>(new Set());
  const [band, setBand] = useState<Confidence | "">("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const listHeadingRef = useRef<HTMLParagraphElement>(null);

  const entries = useMemo(() => (trailQ.data ? flattenTrail(trailQ.data) : []), [trailQ.data]);
  const counts = countByState(entries);
  const linkedEntry = linkedEdge ? entries.find((e) => e.edge.edge_id === linkedEdge) : undefined;
  // open on the linked connection's tab, else the review queue, or on what
  // was accepted when nothing is left to review. Chosen once, on arrival:
  // reviewing the last pending connection then says so, rather than the
  // page jumping to another tab under the reader.
  const openingTab: EdgeUserState =
    linkedEntry?.edge.user_state ?? (counts.pending === 0 && counts.accepted > 0 ? "accepted" : "pending");
  if (tab === null && trailQ.data) setTab(openingTab);
  const activeTab: EdgeUserState = tab ?? openingTab;
  const inTab = entries.filter((e) => e.edge.user_state === activeTab);
  const typeCounts = RELATIONSHIP_TYPES.map((t) => [t, inTab.filter((e) => e.type === t).length] as const).filter(([, n]) => n > 0);
  const visible = filterTrail(entries, { state: activeTab, types, band: band || undefined, query });
  const filtered = types.size > 0 || band !== "" || query.trim() !== "";
  const selectedVisible = visible.filter((e) => selected.has(e.edge.edge_id));

  const seedId = trailQ.data?.seed_paper_id ?? workspaceQ.data?.seed_paper_id ?? "";
  // older backends send no seed title with the trail; fetch it (shared cache with the overview)
  const seedPaperQ = useSWR(seedId && trailQ.data && !trailQ.data.seed?.title ? ["paper", seedId] : null, () => papersApi.get(seedId));
  const seed: Seed = {
    id: seedId,
    title: trailQ.data?.seed?.title ?? seedPaperQ.data?.title ?? null,
    year: trailQ.data?.seed?.year ?? seedPaperQ.data?.year ?? null,
  };

  const scrolledTo = useRef<string | null>(null);
  useEffect(() => {
    if (!linkedEntry || scrolledTo.current === linkedEntry.edge.edge_id) return;
    scrolledTo.current = linkedEntry.edge.edge_id;
    const el = document.querySelector<HTMLElement>(`[data-trail-focus="${CSS.escape(linkedEntry.edge.edge_id)}"]`);
    el?.scrollIntoView({ block: "center" });
    el?.focus({ preventScroll: true });
  }, [linkedEntry]);

  function applyStates(changes: Map<string, EdgeUserState>) {
    trailQ.mutate(
      (current?: GroupedTrail) =>
        current && {
          ...current,
          groups: Object.fromEntries(
            Object.entries(current.groups).map(([type, list]) => [
              type,
              list.map((e) => (changes.has(e.edge.edge_id) ? { ...e, edge: { ...e.edge, user_state: changes.get(e.edge.edge_id)! } } : e)),
            ]),
          ) as GroupedTrail["groups"],
        },
      { revalidate: false },
    );
    // the overview's trail summary and the workspace counts move with the decision
    void mutateGlobal(["ws-trail", id]);
    void mutateGlobal(["workspace", id]);
  }

  /** After a decision the row leaves this tab; keep keyboard focus in the
   * list by moving it to the next row, or to the list heading. */
  function focusAfter(edgeId: string) {
    const idx = visible.findIndex((e) => e.edge.edge_id === edgeId);
    const next = visible[idx + 1] ?? visible[idx - 1];
    requestAnimationFrame(() => {
      const el = next ? document.querySelector<HTMLElement>(`[data-trail-focus="${next.edge.edge_id}"]`) : null;
      (el ?? listHeadingRef.current)?.focus();
    });
  }

  async function decide(entry: TrailEntry, state: EdgeUserState) {
    await workspaces.setEdgeState(id, entry.edge.edge_id, state);
    focusAfter(entry.edge.edge_id);
    applyStates(new Map([[entry.edge.edge_id, state]]));
    setSelected((s) => {
      const next = new Set(s);
      next.delete(entry.edge.edge_id);
      return next;
    });
    setAnnouncement(`${DONE_TEXT[state]}: ${entry.target.title ?? entry.target.id}.`);
  }

  async function decideSelected(state: EdgeUserState) {
    const targets = selectedVisible;
    if (targets.length === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    const results = await Promise.allSettled(targets.map((e) => workspaces.setEdgeState(id, e.edge.edge_id, state)));
    const done = new Map<string, EdgeUserState>();
    results.forEach((r, i) => {
      if (r.status === "fulfilled") done.set(targets[i].edge.edge_id, state);
    });
    applyStates(done);
    setSelected(new Set([...selected].filter((edgeId) => !done.has(edgeId))));
    const failed = targets.length - done.size;
    if (failed > 0) setBulkError(`${failed} of ${targets.length} didn't save. They're still selected; try again.`);
    setAnnouncement(`${DONE_TEXT[state]}: ${done.size} connection${done.size === 1 ? "" : "s"}.`);
    setBulkBusy(false);
    listHeadingRef.current?.focus();
  }

  function clearFilters() {
    setTypes(new Set());
    setBand("");
    setQuery("");
  }

  if (!ready) return null;

  if (workspaceQ.error) {
    return (
      <PageShell>
        <WorkspaceLoadError error={workspaceQ.error} onRetry={() => workspaceQ.mutate()} />
      </PageShell>
    );
  }

  const workspace = workspaceQ.data;

  return (
    <PageShell>
      <div className="selection:bg-[rgba(93,240,168,0.28)] selection:text-white">
        <header className="border-b pb-7" style={{ borderColor: C.lineStrong }}>
          {workspace ? (
            <Link
              href={`/workspace/${id}`}
              className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm text-sm hover:text-white sm:min-h-0 ${focusRing}`}
              style={{ color: C.muted }}
            >
              <ArrowLeft className="size-4" aria-hidden />
              {workspace.title}
            </Link>
          ) : (
            <div className="h-5 w-48 motion-safe:animate-pulse rounded" style={{ background: "rgba(255,255,255,.08)" }} />
          )}
          <h1 className="mt-3 text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Research trail</h1>
          {trailQ.data && (
            <p className="mt-3 max-w-[70ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
              {entries.length === 0 ? (
                "How other papers connect to the seed paper, each with the evidence behind it."
              ) : (
                <>
                  <span className="tabular-nums">{entries.length}</span> connection{entries.length === 1 ? "" : "s"} from{" "}
                  <Link
                    href={`/seed/${seed.id}`}
                    className={`rounded-sm font-medium underline decoration-[rgba(93,240,168,0.45)] underline-offset-4 hover:text-white ${focusRing}`}
                    style={{ color: C.ink }}
                  >
                    {seed.title ?? "the seed paper"}
                  </Link>
                  . Open a connection to see the evidence, then accept or reject it.
                </>
              )}
            </p>
          )}
        </header>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>

        {trailQ.error ? (
          <div className="mt-8 rounded-2xl p-6" style={panel}>
            <InlineError message="Could not load the research trail." />
            <button
              type="button"
              onClick={() => trailQ.mutate()}
              className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`}
              style={primaryButton}
            >
              Try again
            </button>
          </div>
        ) : !trailQ.data || !workspace ? (
          <div role="status" className="mt-8 space-y-3">
            <span className="sr-only">Loading the research trail…</span>
            <Skeleton className="h-11 w-80 max-w-full" />
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-28 w-full" />
          </div>
        ) : entries.length === 0 ? (
          <div className="mt-8 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <h2 className="text-lg font-bold">No connections yet</h2>
            <p className="mx-auto mt-2 max-w-[56ch] text-sm leading-relaxed" style={{ color: C.muted }}>
              {workspace.source_run_id
                ? "No rule linked any paper from this workspace's discovery run to the seed paper, so there is nothing to review."
                : "Connections are found when a workspace is created from discovery results. This one started from the seed paper alone."}
            </p>
            <div className="mt-6 flex justify-center">
              <Link
                href={workspace.source_run_id ? `/discover/${workspace.seed_paper_id}?run=${workspace.source_run_id}` : `/discover/${workspace.seed_paper_id}`}
                className={`rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`}
                style={primaryButton}
              >
                {workspace.source_run_id ? "Open the discovery results" : "Discover related papers"}
              </Link>
            </div>
          </div>
        ) : (
          <>
            <div className="mt-7 space-y-4">
              <div role="group" aria-label="Review state" className="flex flex-wrap gap-2">
                {TABS.map((t) => {
                  const on = activeTab === t.state;
                  return (
                    <button
                      key={t.state}
                      type="button"
                      aria-pressed={on}
                      onClick={() => {
                        setTab(t.state);
                        setSelected(new Set());
                      }}
                      className={`inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-sm font-semibold transition-colors sm:min-h-10 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
                      style={on ? primaryButton : quietButton}
                    >
                      {t.label}
                      <span className="tabular-nums" style={{ opacity: 0.75 }}>
                        {counts[t.state]}
                      </span>
                    </button>
                  );
                })}
              </div>

              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <label className="relative min-w-0 flex-1">
                  <span className="sr-only">Search this trail</span>
                  <MagnifyingGlass className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2" style={{ color: C.muted }} aria-hidden />
                  <input
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search titles, authors and quoted evidence"
                    className="h-11 w-full rounded-full pl-9 pr-4 text-sm caret-[#5df0a8] outline-none placeholder:text-[#8f9bb8] focus-visible:border-[#5df0a8] sm:h-10"
                    style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
                  />
                </label>
                <label className="sm:w-48">
                  <span className="sr-only">Confidence</span>
                  <select
                    value={band}
                    onChange={(e) => setBand(e.target.value as Confidence | "")}
                    className={`h-11 w-full rounded-full px-4 text-sm sm:h-10 ${focusRing}`}
                    style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink, colorScheme: "dark" }}
                  >
                    <option value="">Any confidence</option>
                    <option value="high">High confidence</option>
                    <option value="medium">Medium confidence</option>
                    <option value="low">Low confidence</option>
                  </select>
                </label>
              </div>

              {typeCounts.length > 1 && (
                <div role="group" aria-label="Relationship types" className="flex flex-wrap gap-1.5">
                  {typeCounts.map(([t, n]) => {
                    const on = types.has(t);
                    return (
                      <button
                        key={t}
                        type="button"
                        aria-pressed={on}
                        onClick={() =>
                          setTypes((prev) => {
                            const next = new Set(prev);
                            if (next.has(t)) next.delete(t);
                            else next.add(t);
                            return next;
                          })
                        }
                        className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors sm:min-h-8 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
                        style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
                      >
                        {RELATIONSHIP_COPY[t].label}
                        <span className="tabular-nums" style={{ opacity: 0.7 }}>
                          {n}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <p ref={listHeadingRef} tabIndex={-1} className="text-sm outline-none" style={{ color: C.muted }}>
                {filtered ? (
                  <>
                    Showing <span className="tabular-nums">{visible.length}</span> of <span className="tabular-nums">{inTab.length}</span>{" "}
                    {TABS.find((t) => t.state === activeTab)!.label.toLowerCase()}
                  </>
                ) : (
                  <>
                    <span className="tabular-nums">{inTab.length}</span> {TABS.find((t) => t.state === activeTab)!.label.toLowerCase()}
                  </>
                )}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {filtered && (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className={`min-h-11 rounded-sm text-sm font-medium underline underline-offset-4 hover:text-white sm:min-h-0 ${focusRing}`}
                    style={{ color: C.muted }}
                  >
                    Clear filters
                  </button>
                )}
                {selectedVisible.length > 0 && (
                  <>
                    <span className="text-sm tabular-nums" style={{ color: C.ink }}>
                      {selectedVisible.length} selected
                    </span>
                    {activeTab !== "accepted" && (
                      <button
                        type="button"
                        disabled={bulkBusy}
                        onClick={() => decideSelected("accepted")}
                        className={`min-h-11 rounded-full px-4 text-sm font-semibold disabled:opacity-60 sm:min-h-9 ${focusRing}`}
                        style={primaryButton}
                      >
                        Accept {selectedVisible.length}
                      </button>
                    )}
                    {activeTab !== "rejected" && (
                      <button
                        type="button"
                        disabled={bulkBusy}
                        onClick={() => decideSelected("rejected")}
                        className={`min-h-11 rounded-full px-4 text-sm font-semibold hover:bg-white/10 disabled:opacity-60 sm:min-h-9 ${focusRing}`}
                        style={quietButton}
                      >
                        Reject {selectedVisible.length}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setSelected(new Set())}
                      className={`min-h-11 rounded-sm text-sm underline underline-offset-4 hover:text-white sm:min-h-0 ${focusRing}`}
                      style={{ color: C.muted }}
                    >
                      Clear selection
                    </button>
                  </>
                )}
              </div>
            </div>
            {bulkError && (
              <div className="mt-2">
                <InlineError message={bulkError} />
              </div>
            )}

            {visible.length === 0 ? (
              <div className="mt-4 rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                <p className="text-sm" style={{ color: C.muted }}>
                  {filtered ? "No connections here match these filters." : TABS.find((t) => t.state === activeTab)!.empty}
                </p>
                {filtered ? (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`}
                    style={quietButton}
                  >
                    Clear filters
                  </button>
                ) : (
                  activeTab === "pending" &&
                  counts.accepted > 0 && (
                    <button
                      type="button"
                      onClick={() => setTab("accepted")}
                      className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`}
                      style={quietButton}
                    >
                      See the {counts.accepted} accepted
                    </button>
                  )
                )}
              </div>
            ) : (
              <div className="mt-4 space-y-8">
                {RELATIONSHIP_TYPES.filter((t) => visible.some((e) => e.type === t)).map((t) => {
                  const group = visible.filter((e) => e.type === t);
                  return (
                    <section key={t} aria-labelledby={`trail-group-${t}`}>
                      <div className="mb-3">
                        <h2 id={`trail-group-${t}`} className="text-lg font-bold tracking-[-0.01em]">
                          {RELATIONSHIP_COPY[t].label}{" "}
                          <span className="font-semibold tabular-nums" style={{ color: C.muted }}>
                            {group.length}
                          </span>
                        </h2>
                        <p className="text-sm" style={{ color: C.muted }}>
                          {RELATIONSHIP_COPY[t].description}
                        </p>
                      </div>
                      <ul className="overflow-hidden rounded-2xl" style={panel}>
                        {group.map((entry) => (
                          <TrailRow
                            key={entry.edge.edge_id}
                            entry={entry}
                            seed={seed}
                            selected={selected.has(entry.edge.edge_id)}
                            defaultOpen={entry.edge.edge_id === linkedEdge}
                            onSelect={() =>
                              setSelected((prev) => {
                                const next = new Set(prev);
                                if (next.has(entry.edge.edge_id)) next.delete(entry.edge.edge_id);
                                else next.add(entry.edge.edge_id);
                                return next;
                              })
                            }
                            onDecide={(state) => decide(entry, state)}
                          />
                        ))}
                      </ul>
                    </section>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </PageShell>
  );
}
