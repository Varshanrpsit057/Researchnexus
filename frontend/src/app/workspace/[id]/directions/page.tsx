"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import {
  ArrowCounterClockwise,
  ArrowLeft,
  ArrowRight,
  Check,
  Crosshair,
  GitBranch,
  Graph,
  MagnifyingGlass,
  Table,
  Warning,
  X,
} from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { papers as papersApi, workspaces } from "@/lib/api/endpoints";
import type { DirectionKind, DirectionUserState, ResearchDirection } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { Timestamp } from "@/components/ui/Timestamp";
import {
  KIND_COPY,
  NO_FILTERS,
  STATE_LABEL,
  countByState,
  filterDirections,
  generationOutcome,
  groupByGap,
  kindOf,
  sortDirections,
  type DirectionFilters,
} from "@/lib/directions";
import { GAP_TYPE_LABEL, sortGaps } from "@/lib/gaps";
import { useIsWide } from "@/lib/use-is-wide";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { WorkingTrail, type PaperKind } from "../compare/parts";
import { DecisionButton, StateMark } from "../gaps/parts";
import { C, InlineError, WorkspaceLoadError, focusRing, panel, primaryButton, quietButton } from "../ui";
import { DirectionDetail, DirectionRow, GapSource, KindGlyph } from "./parts";

export default function DirectionsPage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const { me } = useAuth();
  const router = useRouter();
  const search = useSearchParams();
  const selectedId = search.get("direction");
  const fromGap = search.get("gap"); // arriving from a gap's "Propose directions"
  const { mutate: mutateGlobal } = useSWRConfig();
  const isWide = useIsWide();

  const workspaceQ = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));
  // both shared with the overview and the gaps page
  const gapsQ = useSWR(ready && workspaceQ.data ? ["ws-gaps", id] : null, () => workspaces.listGaps(id));
  const directionsQ = useSWR(ready && workspaceQ.data ? ["ws-directions", id] : null, () => workspaces.listDirections(id));

  const workspace = workspaceQ.data;
  const gaps = useMemo(() => gapsQ.data?.gaps ?? [], [gapsQ.data]);
  const directions = useMemo(() => directionsQ.data?.directions ?? [], [directionsQ.data]);
  const members = useMemo(() => workspace?.papers.map((p) => p.paper_id) ?? [], [workspace]);
  const accepted = useMemo(() => sortGaps(gaps.filter((g) => g.user_state === "accepted")), [gaps]);
  const perGap = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of directions) m.set(d.gap_id, (m.get(d.gap_id) ?? 0) + 1);
    return m;
  }, [directions]);

  const paperIds = useMemo(() => [...new Set(directions.flatMap((d) => d.related_papers))].sort(), [directions]);
  const titlesQ = useSWR(paperIds.length ? ["ws-paper-titles", ...paperIds] : null, async () => {
    const found = await Promise.all(paperIds.map((pid) => papersApi.get(pid).catch(() => null)));
    const titles: Record<string, string> = {};
    for (const p of found) {
      if (!p) continue;
      titles[p.id] = p.title;
      void mutateGlobal(["paper", p.id], p, { revalidate: false });
    }
    return titles;
  });

  // which accepted gaps the next run proposes from: chosen once the data arrives, then the reader's
  const [chosen, setChosen] = useState<string[] | null>(null);
  if (chosen === null && gapsQ.data && directionsQ.data) {
    const linked = fromGap && accepted.some((g) => g.gap_id === fromGap) ? [fromGap] : null;
    setChosen(linked ?? accepted.filter((g) => !perGap.has(g.gap_id)).map((g) => g.gap_id));
  }
  const picked = (chosen ?? []).filter((gid) => accepted.some((g) => g.gap_id === gid));

  const [filters, setFilters] = useState<DirectionFilters>(NO_FILTERS);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ReturnType<typeof generationOutcome> | null>(null);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [decideError, setDecideError] = useState<{ id: string; message: string } | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const focusOnOpen = useRef(false);

  const noKey = me != null && !me.has_working_llm_key;
  const counts = countByState(directions);
  const gapStatements = useMemo(() => Object.fromEntries(gaps.map((g) => [g.gap_id, g.statement])), [gaps]);
  const shown = filterDirections(directions, filters, gapStatements, titlesQ.data ?? {});
  const groups = groupByGap(shown, gaps);
  const ordered = groups.flatMap((g) => g.directions);
  const selected = selectedId ? (directions.find((d) => d.direction_id === selectedId) ?? null) : null;
  // wide screens always show a direction: the chosen one, else the first shown
  const detail = selected ?? (isWide && !selectedId ? (ordered[0] ?? null) : null);
  const toReview = sortDirections(directions.filter((d) => d.user_state === "candidate"));
  const nextToReview = detail ? (toReview.find((d) => d.direction_id !== detail.direction_id) ?? null) : null;
  const kinds = [...new Set(directions.map(kindOf))];
  const gapsWithDirections = new Set(directions.map((d) => d.gap_id)).size;

  const kindOfPaper = (paperId: string): PaperKind =>
    paperId === workspace?.seed_paper_id ? "seed" : members.includes(paperId) ? "member" : "connected";

  function select(directionId: string | null, fromUser = true) {
    if (directionId && fromUser && !isWide) {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      focusOnOpen.current = true;
    }
    router.replace(
      directionId ? `/workspace/${id}/directions?direction=${encodeURIComponent(directionId)}` : `/workspace/${id}/directions`,
      { scroll: false },
    );
  }

  function closeSheet() {
    select(null, false);
    const back = returnFocus.current;
    returnFocus.current = null;
    if (back) requestAnimationFrame(() => back.focus());
  }

  const sheetOpen = !isWide && detail != null;
  const openId = detail?.direction_id;
  useEffect(() => {
    if (focusOnOpen.current && sheetOpen) {
      focusOnOpen.current = false;
      headingRef.current?.focus();
    }
  }, [sheetOpen, openId]);
  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeSheet();
    const root = document.documentElement;
    const before = root.style.overflow;
    root.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      root.style.overflow = before;
      window.removeEventListener("keydown", onKey);
    };
  });

  function toggleGap(gapId: string) {
    setChosen((prev) => {
      const now = prev ?? [];
      return now.includes(gapId) ? now.filter((g) => g !== gapId) : [...now, gapId];
    });
  }

  async function run() {
    if (running || picked.length === 0) return;
    setRunning(true);
    setRunError(null);
    setOutcome(null);
    setAnnouncement(`Proposing directions from ${picked.length} gap${picked.length === 1 ? "" : "s"}.`);
    try {
      const res = await workspaces.generateDirections(id, picked);
      await mutateGlobal(["ws-directions", id], { directions: res.directions }, { revalidate: false });
      void mutateGlobal(["workspace", id]);
      const out = generationOutcome(res);
      setOutcome(out);
      setFilters((f) => ({ ...f, state: "candidate" }));
      setAnnouncement(out.headline);
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      setRunError(
        err?.code === "llm_key_required"
          ? "No working LLM provider key is saved. Add one in Settings to propose directions."
          : err?.status === 422
            ? "Choose at least one accepted gap to propose directions from."
            : err
              ? "The run didn't finish. Try again in a moment."
              : "The server couldn't be reached. Check the connection and try again.",
      );
      setAnnouncement("The run didn't finish.");
    } finally {
      setRunning(false);
    }
  }

  async function decide(d: ResearchDirection, state: DirectionUserState) {
    setDeciding(d.direction_id);
    setDecideError(null);
    const key = ["ws-directions", id];
    const swap = (to: ResearchDirection) => (data: { directions: ResearchDirection[] } | undefined) =>
      data ? { directions: data.directions.map((x) => (x.direction_id === to.direction_id ? to : x)) } : data;
    // keep it on screen after it leaves the filter it was found under
    if (selectedId !== d.direction_id) select(d.direction_id, false);
    await mutateGlobal(key, swap({ ...d, user_state: state }), { revalidate: false });
    try {
      const saved = await workspaces.setDirectionState(id, d.direction_id, state);
      await mutateGlobal(key, swap(saved), { revalidate: false });
      void mutateGlobal(["workspace", id]);
      setAnnouncement(state === "candidate" ? "Moved back to review." : `Direction ${state}.`);
    } catch {
      await mutateGlobal(key, swap(d), { revalidate: false });
      setDecideError({ id: d.direction_id, message: "That decision wasn't saved. Try again." });
      setAnnouncement("That decision wasn't saved.");
    } finally {
      setDeciding(null);
    }
  }

  if (!ready) return null;
  if (workspaceQ.error) {
    return (
      <PageShell>
        <WorkspaceLoadError error={workspaceQ.error} onRetry={() => workspaceQ.mutate()} />
      </PageShell>
    );
  }

  const loadError = gapsQ.error || directionsQ.error;
  const loaded = workspace && gapsQ.data && directionsQ.data;
  const gapsToReview = gaps.filter((g) => g.user_state === "candidate").length;

  const detailActions = (d: ResearchDirection) => (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        {d.user_state === "candidate" ? (
          <>
            <DecisionButton primary onClick={() => decide(d, "accepted")} disabled={deciding != null}>
              <Check className="size-4" weight="bold" aria-hidden />
              Accept direction
            </DecisionButton>
            <DecisionButton onClick={() => decide(d, "rejected")} disabled={deciding != null}>
              <X className="size-4" weight="bold" aria-hidden />
              Reject
            </DecisionButton>
          </>
        ) : (
          <>
            <span className="mr-1 text-sm font-semibold">
              <StateMark state={d.user_state} />
            </span>
            <DecisionButton onClick={() => decide(d, "candidate")} disabled={deciding != null}>
              <ArrowCounterClockwise className="size-4" aria-hidden />
              Move back to review
            </DecisionButton>
          </>
        )}
        {d.user_state !== "candidate" && nextToReview && (
          <button
            type="button"
            onClick={() => select(nextToReview.direction_id)}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm px-1 text-sm font-semibold hover:text-white sm:ml-auto sm:min-h-9 ${focusRing}`}
            style={{ color: C.mint }}
          >
            Next to review
            <ArrowRight className="size-4" aria-hidden />
          </button>
        )}
      </div>
      {decideError?.id === d.direction_id && (
        <div className="mt-2">
          <InlineError message={decideError.message} />
        </div>
      )}
      <nav aria-label="This direction elsewhere" className="mt-2.5 flex flex-wrap gap-x-4 text-[13px]" style={{ color: C.muted }}>
        <NavLink href={`/workspace/${id}/gaps?gap=${encodeURIComponent(d.gap_id)}`} icon={<Crosshair className="size-3.5" aria-hidden />}>
          Open its gap
        </NavLink>
        <NavLink href={`/workspace/${id}/trail`} icon={<GitBranch className="size-3.5" aria-hidden />}>
          Trail
        </NavLink>
        <NavLink href={`/workspace/${id}/graph`} icon={<Graph className="size-3.5" aria-hidden />}>
          Graph
        </NavLink>
      </nav>
    </div>
  );

  const detailFor = (d: ResearchDirection) => (
    <DirectionDetail
      ref={headingRef}
      direction={d}
      gap={gaps.find((g) => g.gap_id === d.gap_id) ?? null}
      workspaceId={id}
      kindOf={kindOfPaper}
      proposed={<Timestamp at={d.generated_at} />}
      actions={detailActions(d)}
    />
  );

  return (
    <PageShell maxWidthClassName="max-w-[1320px]">
      <div className="selection:bg-[rgba(93,240,168,0.28)] selection:text-white">
        <header className="border-b pb-6" style={{ borderColor: C.lineStrong }}>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            {workspace ? (
              <Link
                href={`/workspace/${id}`}
                className={`inline-flex min-h-11 min-w-0 items-center gap-1.5 rounded-sm text-sm hover:text-white sm:min-h-0 ${focusRing}`}
                style={{ color: C.muted }}
              >
                <ArrowLeft className="size-4 shrink-0" aria-hidden />
                <span className="truncate">{workspace.title}</span>
              </Link>
            ) : (
              <div className="h-5 w-48 rounded motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.08)" }} />
            )}
            <nav aria-label="Related views" className="flex flex-wrap items-center gap-x-4 text-sm sm:ml-auto" style={{ color: C.muted }}>
              <NavLink href={`/workspace/${id}/gaps`} icon={<Crosshair className="size-4" aria-hidden />}>
                Gaps
              </NavLink>
              <NavLink href={`/workspace/${id}/trail`} icon={<GitBranch className="size-4" aria-hidden />}>
                Trail
              </NavLink>
              <NavLink href={`/workspace/${id}/graph`} icon={<Graph className="size-4" aria-hidden />}>
                Graph
              </NavLink>
              <NavLink href={`/workspace/${id}/compare`} icon={<Table className="size-4" aria-hidden />}>
                Compare
              </NavLink>
            </nav>
          </div>
          <h1 className="mt-3 text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Research directions</h1>
          <p className="mt-3 max-w-[74ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
            {directions.length > 0 ? (
              <>
                <span className="tabular-nums">{directions.length}</span> direction{directions.length === 1 ? "" : "s"} from{" "}
                <span className="tabular-nums">{gapsWithDirections}</span> gap{gapsWithDirections === 1 ? "" : "s"}: <span className="tabular-nums">{counts.candidate}</span> to
                review, <span className="tabular-nums">{counts.accepted}</span> accepted, <span className="tabular-nums">{counts.rejected}</span> rejected. Each keeps
                its gap&apos;s passages and says whether it follows from them or is a hypothesis to test.
              </>
            ) : (
              "Concrete next steps proposed from the gaps you accepted. Each keeps its gap's passages, says whether it follows from them or is a hypothesis to test, and shows how a critique rated it."
            )}
          </p>
        </header>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>

        {!loaded ? (
          loadError ? (
            <div className="mt-8 rounded-2xl p-6" style={panel}>
              <InlineError message="Could not load this workspace's directions." />
              <button
                type="button"
                onClick={() => {
                  void gapsQ.mutate();
                  void directionsQ.mutate();
                }}
                className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`}
                style={primaryButton}
              >
                Try again
              </button>
            </div>
          ) : (
            <div role="status" className="mt-8 space-y-4">
              <span className="sr-only">Loading the directions…</span>
              <div className="h-40 rounded-2xl motion-safe:animate-pulse" style={panel} />
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
                <div className="h-72 rounded-2xl motion-safe:animate-pulse" style={panel} />
                <div className="hidden h-72 rounded-2xl motion-safe:animate-pulse lg:block" style={panel} />
              </div>
            </div>
          )
        ) : accepted.length === 0 && directions.length === 0 ? (
          <div className="mt-8 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <h2 className="text-lg font-bold">Directions start from gaps you accept</h2>
            <p className="mx-auto mt-2 max-w-[60ch] text-sm leading-relaxed" style={{ color: C.muted }}>
              {gapsToReview > 0
                ? `This workspace has ${gapsToReview} gap${gapsToReview === 1 ? "" : "s"} waiting for review. Accept the ones worth pursuing, and propose directions from them here.`
                : "Find the gaps this workspace's papers leave open, accept the ones worth pursuing, and propose directions from them here."}
            </p>
            <Link href={`/workspace/${id}/gaps`} className={`mt-6 inline-flex rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
              {gapsToReview > 0 ? `Review ${gapsToReview} gap${gapsToReview === 1 ? "" : "s"}` : "Find gaps"}
            </Link>
          </div>
        ) : (
          <>
            {/* the starting point: accepted gaps */}
            <section aria-labelledby="dir-run" className="mt-7 rounded-2xl p-5" style={panel}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h2 id="dir-run" className="text-base font-bold">
                  Start from an accepted gap
                </h2>
                <Link href={`/workspace/${id}/gaps`} className={`rounded-sm text-[13px] underline underline-offset-4 hover:text-white ${focusRing}`} style={{ color: C.muted }}>
                  {gapsToReview > 0 ? `${gapsToReview} more gap${gapsToReview === 1 ? "" : "s"} to review` : "All gaps"}
                </Link>
              </div>
              {accepted.length === 0 ? (
                <p className="mt-2 text-[13.5px] leading-relaxed" style={{ color: C.muted }}>
                  No gap is accepted right now, so no new directions can be proposed. The directions below stay, with the gap each came from.
                </p>
              ) : (
                <ul className="mt-3 grid gap-2 md:grid-cols-2" aria-label="Accepted gaps to propose from">
                  {accepted.map((g) => {
                    const on = picked.includes(g.gap_id);
                    const n = perGap.get(g.gap_id) ?? 0;
                    return (
                      <li key={g.gap_id}>
                        <button
                          type="button"
                          aria-pressed={on}
                          onClick={() => toggleGap(g.gap_id)}
                          className={`flex h-full w-full gap-3 rounded-xl px-3.5 py-3 text-left transition-colors ${on ? "" : "hover:bg-white/[0.04]"} ${focusRing}`}
                          style={
                            on
                              ? { background: "rgba(93,240,168,.08)", border: "1px solid rgba(93,240,168,.45)" }
                              : { border: `1px solid ${C.line}` }
                          }
                        >
                          <span
                            aria-hidden
                            className="mt-[3px] flex size-4 shrink-0 items-center justify-center rounded"
                            style={on ? { background: C.mint } : { border: `1.5px solid ${C.lineStrong}` }}
                          >
                            {on && <Check className="size-3" weight="bold" style={{ color: C.mintInk }} />}
                          </span>
                          <span className="min-w-0">
                            <span className="block text-[12.5px]" style={{ color: C.muted }}>
                              {GAP_TYPE_LABEL[g.gap_type] ?? g.gap_type} · {n === 0 ? "no directions yet" : `${n} direction${n === 1 ? "" : "s"}`}
                            </span>
                            <span className="mt-0.5 line-clamp-2 block text-[14px] leading-snug" style={{ color: C.ink }}>
                              {g.statement}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
              {accepted.length > 0 && (
                <div className="mt-4 flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center" style={{ borderColor: C.line }}>
                  <button
                    type="button"
                    onClick={run}
                    disabled={running || noKey || picked.length === 0}
                    className={`inline-flex min-h-11 shrink-0 items-center self-start rounded-full px-5 text-sm font-semibold transition-[opacity,transform] active:scale-[0.97] disabled:opacity-45 sm:self-auto ${focusRing}`}
                    style={primaryButton}
                  >
                    {running
                      ? "Proposing…"
                      : picked.length === 0
                        ? "Propose directions"
                        : `Propose directions from ${picked.length} gap${picked.length === 1 ? "" : "s"}`}
                  </button>
                  <p className="min-w-0 flex-1 text-[13px] leading-snug" style={{ color: noKey ? C.warning : C.muted }}>
                    {noKey ? (
                      <span className="inline-flex items-start gap-1.5">
                        <Warning className="mt-px size-4 shrink-0" weight="bold" aria-hidden />
                        <span>
                          No working LLM provider key is saved, so directions can&apos;t be proposed yet.{" "}
                          <Link href="/settings" className={`rounded-sm font-semibold underline underline-offset-4 ${focusRing}`}>
                            Add a key
                          </Link>
                        </span>
                      </span>
                    ) : picked.length === 0 ? (
                      "Choose the gaps to propose from."
                    ) : (
                      "A model proposes a few directions per gap from the gap alone. One naming anything its evidence doesn't contain is dropped; the rest are critiqued and given a confidence band. Accepted and rejected directions are never overwritten."
                    )}
                  </p>
                </div>
              )}
              {running && (
                <div role="status" className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-4" style={{ borderColor: C.line }}>
                  <WorkingTrail count={Math.max(2, picked.length + 1)} />
                  <p className="text-[13px]" style={{ color: C.muted }}>
                    Proposing directions for each gap, dropping any that outrun its evidence, then critiquing the rest. This can take a minute.
                  </p>
                </div>
              )}
              {outcome && !running && (
                <div role="status" className="mt-4 border-t pt-4 text-[13.5px] leading-relaxed" style={{ borderColor: C.line }}>
                  <p>
                    {outcome.headline}
                    {outcome.notes.length > 0 && <span style={{ color: C.muted }}> {outcome.notes.join(" ")}</span>}
                  </p>
                </div>
              )}
              {runError && (
                <div className="mt-4">
                  <InlineError message={runError} />
                </div>
              )}
            </section>

            {directions.length === 0 ? (
              !running && (
                <div className="mt-8 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                  <h2 className="text-lg font-bold">No directions yet</h2>
                  <p className="mx-auto mt-2 max-w-[60ch] text-sm leading-relaxed" style={{ color: C.muted }}>
                    Choose accepted gaps above and propose directions. Each arrives with its plan, the passages behind it, and how a critique rated it, to
                    accept or reject.
                  </p>
                </div>
              )
            ) : (
              <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
                <section aria-labelledby="dir-list">
                  <h2 id="dir-list" className="sr-only">
                    Directions
                  </h2>
                  <Filters filters={filters} onChange={setFilters} counts={counts} kinds={kinds} />
                  {shown.length === 0 ? (
                    <div className="mt-4 rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                      {filters.state === "candidate" && counts.candidate === 0 && !filters.query && filters.kind === "all" ? (
                        <>
                          <h3 className="text-base font-bold">Nothing left to review</h3>
                          <p className="mx-auto mt-1.5 max-w-[50ch] text-sm" style={{ color: C.muted }}>
                            Every direction has a decision. Look at what you accepted, or propose more from another gap.
                          </p>
                          <button
                            type="button"
                            onClick={() => setFilters({ ...filters, state: "accepted" })}
                            className={`mt-4 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
                            style={quietButton}
                          >
                            Show accepted directions
                          </button>
                        </>
                      ) : (
                        <>
                          <h3 className="text-base font-bold">No directions match</h3>
                          <p className="mx-auto mt-1.5 max-w-[50ch] text-sm" style={{ color: C.muted }}>
                            Nothing here fits these filters.
                          </p>
                          <button
                            type="button"
                            onClick={() => setFilters({ ...NO_FILTERS, state: "all" })}
                            className={`mt-4 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
                            style={quietButton}
                          >
                            Clear the filters
                          </button>
                        </>
                      )}
                    </div>
                  ) : (
                    <div className="mt-4 space-y-6" aria-label={`${filters.state === "all" ? "All directions" : STATE_LABEL[filters.state]}: ${shown.length}`} role="region">
                      {groups.map((group) => (
                        <div key={group.gapId} className="rounded-2xl p-3.5" style={panel}>
                          <GapSource gapId={group.gapId} gap={group.gap} workspaceId={id} count={perGap.get(group.gapId) ?? group.directions.length} />
                          {/* the branch: every direction grows from its gap */}
                          <ul className="relative ml-[6.5px] mt-2 space-y-1 border-l pl-3" style={{ borderColor: "rgba(93,240,168,.3)" }}>
                            {group.directions.map((d) => (
                              <li key={d.direction_id} className="relative">
                                <span aria-hidden className="absolute -left-3 top-6 block h-px w-3" style={{ background: "rgba(93,240,168,.3)" }} />
                                <DirectionRow direction={d} selected={detail?.direction_id === d.direction_id} onSelect={() => select(d.direction_id)} />
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                {isWide && (
                  <div
                    className="sticky top-6 max-h-[calc(100dvh-3rem)] overflow-y-auto overscroll-contain rounded-2xl [scrollbar-color:rgba(150,175,230,.28)_transparent]"
                    style={{ background: "rgba(10,15,32,.82)", border: `1px solid ${C.lineStrong}` }}
                    data-testid="direction-detail"
                  >
                    {detail ? detailFor(detail) : <MissingDirection known={selectedId != null} onClear={() => select(null, false)} />}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {sheetOpen && detail && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Direction details"
          className="fixed inset-0 z-40 overflow-y-auto overscroll-contain"
          style={{ background: "#070a16" }}
          data-testid="direction-detail"
        >
          <div className="sticky top-0 z-10 flex items-center border-b px-2 py-1.5 backdrop-blur-md" style={{ borderColor: C.line, background: "rgba(7,10,22,.9)" }}>
            <button
              type="button"
              onClick={closeSheet}
              className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-sm font-semibold hover:bg-white/10 ${focusRing}`}
              style={{ color: C.muted }}
            >
              <ArrowLeft className="size-4" aria-hidden />
              All directions
            </button>
          </div>
          {detailFor(detail)}
        </div>
      )}
      {!isWide && selectedId && !selected && directionsQ.data && (
        <div className="fixed inset-x-3 bottom-3 z-40 rounded-2xl" style={{ background: "rgba(10,15,32,.96)", border: `1px solid ${C.lineStrong}` }}>
          <MissingDirection known onClear={() => select(null, false)} />
        </div>
      )}
    </PageShell>
  );
}

function MissingDirection({ known, onClear }: { known: boolean; onClear: () => void }) {
  return (
    <div className="px-6 py-10 text-center">
      <p className="text-sm" style={{ color: C.muted }}>
        {known ? "That direction isn't in this workspace any more; a later run replaced it." : "Choose a direction to read its plan and evidence."}
      </p>
      {known && (
        <button type="button" onClick={onClear} className={`mt-3 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={quietButton}>
          Show all directions
        </button>
      )}
    </div>
  );
}

function Filters({
  filters,
  onChange,
  counts,
  kinds,
}: {
  filters: DirectionFilters;
  onChange: (f: DirectionFilters) => void;
  counts: Record<DirectionUserState | "all", number>;
  kinds: DirectionKind[];
}) {
  const states: (DirectionUserState | "all")[] = ["candidate", "accepted", "rejected", "all"];
  return (
    <div className="space-y-2.5">
      <div role="group" aria-label="Show directions" className="flex flex-wrap gap-1.5">
        {states.map((s) => {
          const on = filters.state === s;
          return (
            <button
              key={s}
              type="button"
              aria-pressed={on}
              onClick={() => onChange({ ...filters, state: s })}
              className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors sm:min-h-9 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
              style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
            >
              {s === "all" ? "All" : STATE_LABEL[s]}
              <span className="tabular-nums" style={{ opacity: 0.75 }}>
                {counts[s]}
              </span>
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <label className="relative flex basis-full items-center">
          <span className="sr-only">Search the directions</span>
          <MagnifyingGlass className="pointer-events-none absolute left-3 size-4" style={{ color: C.muted }} aria-hidden />
          <input
            type="search"
            value={filters.query}
            onChange={(e) => onChange({ ...filters, query: e.target.value })}
            placeholder="Search proposals, methods, passages"
            className={`min-h-11 w-full rounded-full bg-transparent pl-9 pr-3 text-[13.5px] caret-[#5df0a8] outline-none placeholder:text-[#8f9bb8] sm:min-h-9 ${focusRing}`}
            style={{ ...quietButton, color: C.ink }}
          />
        </label>
        {kinds.length > 1 && (
          <div role="group" aria-label="Kind of direction" className="flex gap-1.5">
            {(["all", "evidence_backed_inference", "llm_hypothesis"] as const).map((k) => {
              const on = filters.kind === k;
              return (
                <button
                  key={k}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onChange({ ...filters, kind: k })}
                  className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-[13px] transition-colors sm:min-h-9 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
                  style={on ? { background: "rgba(93,240,168,.14)", border: "1px solid rgba(93,240,168,.45)", color: C.ink } : { ...quietButton, color: C.muted }}
                >
                  {k !== "all" && <KindGlyph kind={k} size={11} />}
                  {k === "all" ? "Every kind" : k === "llm_hypothesis" ? "Hypotheses" : KIND_COPY[k].label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function NavLink({ href, icon, children }: { href: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Link href={href} className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm hover:text-white sm:min-h-0 ${focusRing}`}>
      {icon}
      {children}
    </Link>
  );
}
