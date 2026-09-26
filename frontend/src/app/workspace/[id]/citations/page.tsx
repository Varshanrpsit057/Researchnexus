"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ArrowLeft, ArrowSquareOut, ChatCircleText, Crosshair, DownloadSimple, GitBranch, Graph, MagnifyingGlass, Table } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import type { CitationFormat, LedgerPaper } from "@/lib/api/types";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import {
  SORT_LABEL,
  STYLE_LABEL,
  USE_COPY,
  USE_KINDS,
  bibliography,
  citable,
  filterPapers,
  sortPapers,
  type CitedIn,
  type SortKey,
} from "@/lib/citations";
import { usePreference } from "@/lib/preferences";
import { useIsWide } from "@/lib/use-is-wide";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import type { PaperKind } from "../compare/parts";
import { C, InlineError, WorkspaceLoadError, focusRing, panel, primaryButton, quietButton } from "../ui";
import { LedgerRow, PaperDossier } from "./parts";

const STYLES: CitationFormat[] = ["apa", "ieee", "bibtex"];

export default function CitationsPage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const router = useRouter();
  const selectedId = useSearchParams().get("paper");
  const isWide = useIsWide();

  const workspaceQ = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));
  const ledgerQ = useSWR(ready && workspaceQ.data ? ["ws-citations", id] : null, () => workspaces.citationLedger(id));

  const workspace = workspaceQ.data;
  const papers = useMemo(() => ledgerQ.data?.papers ?? [], [ledgerQ.data]);
  const seedReferences = ledgerQ.data?.seed_references ?? [];
  const ledgerIds = useMemo(() => new Set(papers.map((p) => p.paper_id)), [papers]);

  const [citedIn, setCitedIn] = useState<CitedIn>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("cited");
  // opens in the reference style chosen in Settings, until the reader picks another here
  const preferredStyle = usePreference("referenceStyle");
  const [chosenStyle, setStyle] = useState<CitationFormat | null>(null);
  const style = chosenStyle ?? preferredStyle;
  const [announcement, setAnnouncement] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const focusOnOpen = useRef(false);

  const shown = sortPapers(filterPapers(papers, citedIn, query), sort);
  const selected = selectedId ? (papers.find((p) => p.paper_id === selectedId) ?? null) : null;
  const detail = selected ?? (isWide && !selectedId ? (shown[0] ?? null) : null);
  const totals = Object.fromEntries(USE_KINDS.map((k) => [k, papers.reduce((n, p) => n + p.counts[k], 0)])) as Record<(typeof USE_KINDS)[number], number>;
  const allUses = USE_KINDS.reduce((n, k) => n + totals[k], 0);
  const matchedRefs = seedReferences.filter((r) => r.paper_id).length;
  const kindOf = (p: LedgerPaper): PaperKind => (p.role === "seed" ? "seed" : "member");
  const papersIn = (c: CitedIn) => filterPapers(papers, c, "").length;
  const exportable = papers.filter(citable);

  function select(paperId: string | null, fromUser = true) {
    if (paperId && fromUser && !isWide) {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      focusOnOpen.current = true;
    }
    router.replace(paperId ? `/workspace/${id}/citations?paper=${encodeURIComponent(paperId)}` : `/workspace/${id}/citations`, { scroll: false });
  }

  function closeSheet() {
    select(null, false);
    const back = returnFocus.current;
    returnFocus.current = null;
    if (back) requestAnimationFrame(() => back.focus());
  }

  const sheetOpen = !isWide && detail != null;
  const openId = detail?.paper_id;
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

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(bibliography(papers, style));
      setAnnouncement(`${exportable.length} ${STYLE_LABEL[style]} references copied.`);
    } catch {
      setAnnouncement("Couldn't copy the references.");
    }
  }

  function downloadBib() {
    const url = URL.createObjectURL(new Blob([bibliography(papers, "bibtex") + "\n"], { type: "application/x-bibtex" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(workspace?.title ?? "workspace").replace(/[^\w-]+/g, "-").slice(0, 60)}.bib`;
    a.click();
    URL.revokeObjectURL(url);
    setAnnouncement("BibTeX file downloaded.");
  }

  if (!ready) return null;
  if (workspaceQ.error) {
    return (
      <PageShell>
        <WorkspaceLoadError error={workspaceQ.error} onRetry={() => workspaceQ.mutate()} />
      </PageShell>
    );
  }

  const footerFor = (p: LedgerPaper) => (
    <nav aria-label="This paper elsewhere" className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]" style={{ color: C.muted }}>
      <NavLink href={p.role === "seed" ? `/seed/${p.paper_id}` : `/papers/${p.paper_id}`} icon={<ArrowSquareOut className="size-3.5" aria-hidden />}>
        Open paper
      </NavLink>
      <NavLink href={`/workspace/${id}/graph?paper=${encodeURIComponent(p.paper_id)}`} icon={<Graph className="size-3.5" aria-hidden />}>
        Show in graph
      </NavLink>
      <NavLink href={`/workspace/${id}/trail`} icon={<GitBranch className="size-3.5" aria-hidden />}>
        Trail
      </NavLink>
      <NavLink href={`/workspace/${id}/chat`} icon={<ChatCircleText className="size-3.5" aria-hidden />}>
        Ask about it
      </NavLink>
      <NavLink href={`/workspace/${id}/compare`} icon={<Table className="size-3.5" aria-hidden />}>
        Compare
      </NavLink>
    </nav>
  );

  const dossierFor = (p: LedgerPaper) => (
    <PaperDossier
      ref={headingRef}
      paper={p}
      kind={kindOf(p)}
      workspaceId={id}
      style={style}
      onStyle={setStyle}
      seedReferences={seedReferences}
      ledgerIds={ledgerIds}
      onPick={(pid) => select(pid)}
      onAnnounce={setAnnouncement}
      footer={footerFor(p)}
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
              <NavLink href={`/workspace/${id}/trail`} icon={<GitBranch className="size-4" aria-hidden />}>
                Trail
              </NavLink>
              <NavLink href={`/workspace/${id}/graph`} icon={<Graph className="size-4" aria-hidden />}>
                Graph
              </NavLink>
              <NavLink href={`/workspace/${id}/chat`} icon={<ChatCircleText className="size-4" aria-hidden />}>
                Ask
              </NavLink>
              <NavLink href={`/workspace/${id}/compare`} icon={<Table className="size-4" aria-hidden />}>
                Compare
              </NavLink>
              <NavLink href={`/workspace/${id}/gaps`} icon={<Crosshair className="size-4" aria-hidden />}>
                Gaps
              </NavLink>
            </nav>
          </div>
          <h1 className="mt-3 text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Citations</h1>
          <p className="mt-3 max-w-[76ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
            {ledgerQ.data ? (
              <>
                <span className="tabular-nums">{papers.length}</span> paper{papers.length === 1 ? "" : "s"}
                {allUses > 0 ? (
                  <>
                    , cited <span className="tabular-nums">{allUses}</span> time{allUses === 1 ? "" : "s"} in this workspace:{" "}
                    {USE_KINDS.filter((k) => totals[k] > 0)
                      .map((k) => `${totals[k]} in ${USE_COPY[k].label.toLowerCase()}`)
                      .join(", ")}
                    .
                  </>
                ) : (
                  ", none cited in the workspace yet."
                )}
                {seedReferences.length > 0 && (
                  <>
                    {" "}
                    The seed paper lists <span className="tabular-nums">{seedReferences.length}</span> references; the trail matched{" "}
                    <span className="tabular-nums">{matchedRefs}</span> to a paper.
                  </>
                )}
              </>
            ) : (
              "Every paper in the workspace, its reference, and every place the workspace cites it, with the passage each citation rests on."
            )}
          </p>
        </header>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>

        {!workspace || !ledgerQ.data ? (
          ledgerQ.error ? (
            <div className="mt-8 rounded-2xl p-6" style={panel}>
              <InlineError message="Could not load this workspace's citations." />
              <button type="button" onClick={() => ledgerQ.mutate()} className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                Try again
              </button>
            </div>
          ) : (
            <div role="status" className="mt-8 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
              <span className="sr-only">Loading the citations…</span>
              <div className="space-y-3">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="h-24 rounded-2xl motion-safe:animate-pulse" style={panel} />
                ))}
              </div>
              <div className="hidden h-[460px] rounded-2xl motion-safe:animate-pulse lg:block" style={panel} />
            </div>
          )
        ) : (
          <>
            {/* how to read and export the references */}
            <section aria-label="References" className="mt-7 flex flex-col gap-3 rounded-2xl p-4 sm:flex-row sm:flex-wrap sm:items-center" style={panel}>
              <div role="group" aria-label="Reference style" className="flex gap-1.5">
                {STYLES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    aria-pressed={style === s}
                    onClick={() => setStyle(s)}
                    className={`min-h-11 rounded-full px-3.5 text-[13px] font-medium transition-colors sm:min-h-9 ${style === s ? "" : "hover:bg-white/10"} ${focusRing}`}
                    style={style === s ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
                  >
                    {STYLE_LABEL[s]}
                  </button>
                ))}
              </div>
              <p className="min-w-0 flex-1 text-[13px] leading-snug" style={{ color: C.muted }}>
                References are formatted by rule from each paper&apos;s own metadata, never generated. <span className="tabular-nums">{exportable.length}</span> of{" "}
                <span className="tabular-nums">{papers.length}</span> can be built.
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={copyAll}
                  disabled={exportable.length === 0}
                  className={`inline-flex min-h-11 items-center rounded-full px-4 text-[13px] font-semibold transition-colors hover:bg-white/10 disabled:opacity-45 sm:min-h-9 ${focusRing}`}
                  style={quietButton}
                >
                  Copy all as {STYLE_LABEL[style]}
                </button>
                <button
                  type="button"
                  onClick={downloadBib}
                  disabled={exportable.length === 0}
                  className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-4 text-[13px] font-semibold transition-colors hover:bg-white/10 disabled:opacity-45 sm:min-h-9 ${focusRing}`}
                  style={quietButton}
                >
                  <DownloadSimple className="size-4" aria-hidden />
                  Download .bib
                </button>
              </div>
            </section>

            <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
              <section aria-labelledby="ledger">
                <h2 id="ledger" className="sr-only">
                  Papers
                </h2>
                <div className="space-y-2.5">
                  <div role="group" aria-label="Cited in" className="flex flex-wrap gap-1.5">
                    {(["all", ...USE_KINDS, "none"] as CitedIn[]).map((c) => {
                      const n = papersIn(c);
                      if (c !== "all" && c !== "none" && n === 0) return null;
                      const on = citedIn === c;
                      return (
                        <button
                          key={c}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setCitedIn(c)}
                          className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors sm:min-h-9 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
                          style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
                        >
                          {c === "all" ? "All papers" : c === "none" ? "Not cited yet" : `In ${USE_COPY[c].label.toLowerCase()}`}
                          <span className="tabular-nums" style={{ opacity: 0.75 }}>
                            {n}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <label className="relative flex basis-full items-center sm:basis-auto sm:min-w-[220px] sm:flex-1">
                      <span className="sr-only">Search the citations</span>
                      <MagnifyingGlass className="pointer-events-none absolute left-3 size-4" style={{ color: C.muted }} aria-hidden />
                      <input
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search titles, authors, cited passages"
                        className={`min-h-11 w-full rounded-full bg-transparent pl-9 pr-3 text-[13.5px] caret-[#5df0a8] outline-none placeholder:text-[#8f9bb8] sm:min-h-9 ${focusRing}`}
                        style={{ ...quietButton, color: C.ink }}
                      />
                    </label>
                    <label>
                      <span className="sr-only">Sort</span>
                      <select
                        value={sort}
                        onChange={(e) => setSort(e.target.value as SortKey)}
                        className={`min-h-11 rounded-full bg-transparent px-3 text-[13px] [color-scheme:dark] sm:min-h-9 ${focusRing}`}
                        style={{ ...quietButton, color: C.ink }}
                      >
                        {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => (
                          <option key={k} value={k}>
                            {SORT_LABEL[k]}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </div>

                {shown.length === 0 ? (
                  <div className="mt-4 rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                    <h3 className="text-base font-bold">No papers match</h3>
                    <p className="mx-auto mt-1.5 max-w-[50ch] text-sm" style={{ color: C.muted }}>
                      Nothing here fits this search and filter.
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        setCitedIn("all");
                        setQuery("");
                      }}
                      className={`mt-4 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
                      style={quietButton}
                    >
                      Show every paper
                    </button>
                  </div>
                ) : (
                  <ul className="mt-4 space-y-1.5 rounded-2xl p-1.5" style={panel} aria-label={`Papers: ${shown.length}`}>
                    {shown.map((p) => (
                      <li key={p.paper_id}>
                        <LedgerRow paper={p} kind={kindOf(p)} selected={detail?.paper_id === p.paper_id} onSelect={() => select(p.paper_id)} />
                      </li>
                    ))}
                  </ul>
                )}
                {allUses === 0 && (
                  <p className="mt-4 px-1 text-[13px] leading-relaxed" style={{ color: C.muted }}>
                    Nothing in the workspace cites these papers yet. Ask a question, compare the papers or look for gaps: every passage used is
                    recorded here, under its paper.
                  </p>
                )}
              </section>

              {isWide && (
                <div
                  className="sticky top-6 max-h-[calc(100dvh-3rem)] overflow-y-auto overscroll-contain rounded-2xl [scrollbar-color:rgba(150,175,230,.28)_transparent]"
                  style={{ background: "rgba(10,15,32,.82)", border: `1px solid ${C.lineStrong}` }}
                  data-testid="citation-detail"
                >
                  {detail ? (
                    dossierFor(detail)
                  ) : (
                    <p className="px-6 py-10 text-center text-sm" style={{ color: C.muted }}>
                      {selectedId ? "That paper isn't in this workspace any more." : "Choose a paper to see where the workspace cites it."}
                    </p>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {sheetOpen && detail && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Paper citations"
          className="fixed inset-0 z-40 overflow-y-auto overscroll-contain"
          style={{ background: "#070a16" }}
          data-testid="citation-detail"
        >
          <div className="sticky top-0 z-10 flex items-center border-b px-2 py-1.5" style={{ borderColor: C.line, background: "#070a16" }}>
            <button
              type="button"
              onClick={closeSheet}
              className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-sm font-semibold hover:bg-white/10 ${focusRing}`}
              style={{ color: C.muted }}
            >
              <ArrowLeft className="size-4" aria-hidden />
              All papers
            </button>
          </div>
          {dossierFor(detail)}
        </div>
      )}
    </PageShell>
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
