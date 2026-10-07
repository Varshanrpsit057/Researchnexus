"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { ArrowRight, CheckCircle, CircleDashed, FilePdf, MagnifyingGlass, UploadSimple } from "@phosphor-icons/react/dist/ssr";
import { papers as papersApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { useJobPolling } from "@/lib/api/hooks";
import type { Paper } from "@/lib/api/types";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { recordRecentPaper, useRecentPapers } from "@/lib/local-history";
import { MAX_PDF_MB, MAX_PDF_PAGES, checkPdfFile, uploadErrorMessage } from "@/lib/paper-upload";
import { COVERAGE_LABEL } from "@/lib/coverage";
import { authorLine } from "@/lib/discovery-results";
import {
  LIBRARY_SORTS,
  LIBRARY_VIEWS,
  filterLibrary,
  fromBrowser,
  mergeLibrary,
  nextStep,
  rolesLine,
  sortLibrary,
  viewCounts,
  type LibraryEntry,
  type LibrarySort,
  type LibraryView,
} from "@/lib/library";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { Timestamp } from "@/components/ui/Timestamp";
import { C, COVERAGE_TONE, InlineError, focusRing, panel, primaryButton, quietButton } from "@/components/cinematic/ui";

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; name: string }
  | { phase: "reading"; name: string; paperId: string; jobId: string }
  | { phase: "error"; message: string };

const PAGE = 40;

export default function PapersPage() {
  const { ready } = useRequireAuth();
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const libraryQ = useSWR(ready ? "library" : null, () => papersApi.library());

  // uploads this browser made before uploads were credited to an account
  const recent = useRecentPapers();
  const unknownIds = useMemo(() => {
    const known = new Set(libraryQ.data?.papers.map((p) => p.id) ?? []);
    return libraryQ.data ? recent.filter((r) => !known.has(r.paperId)) : [];
  }, [libraryQ.data, recent]);
  const browserQ = useSWR(unknownIds.length ? ["library-browser", ...unknownIds.map((r) => r.paperId)] : null, async () => {
    const found = await Promise.allSettled(unknownIds.map((r) => papersApi.get(r.paperId)));
    return found.flatMap((f, i) => (f.status === "fulfilled" ? [fromBrowser(f.value as Paper, unknownIds[i].addedAt)] : []));
  });

  const entries = useMemo(() => mergeLibrary(libraryQ.data?.papers ?? [], browserQ.data ?? []), [libraryQ.data, browserQ.data]);
  const [view, setView] = useState<LibraryView>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<LibrarySort>("recent");
  const [shown, setShown] = useState(PAGE);
  const visible = useMemo(() => sortLibrary(filterLibrary(entries, view, query), sort), [entries, view, query, sort]);
  const counts = viewCounts(entries);

  if (!ready) return null;

  return (
    <PageShell>
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3 border-b pb-6" style={{ borderColor: C.lineStrong }}>
        <div>
          <h1 className="text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Papers</h1>
          <p className="mt-3 max-w-[64ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
            Every paper you have uploaded, analysed, searched from or collected into a workspace, on any device. Upload a PDF to start
            from a new one.
          </p>
        </div>
        {libraryQ.data && (
          <p className="text-sm tabular-nums" style={{ color: C.muted }}>
            {libraryQ.data.counts.papers} paper{libraryQ.data.counts.papers === 1 ? "" : "s"} · {libraryQ.data.counts.analyzed} analysed ·{" "}
            {libraryQ.data.counts.workspaces} workspace{libraryQ.data.counts.workspaces === 1 ? "" : "s"}
          </p>
        )}
      </header>

      <UploadPanel
        onUploaded={(paperId) => {
          void mutate("library");
          router.push(`/papers/${paperId}`);
        }}
      />

      <section aria-labelledby="library-heading" className="mt-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="library-heading" className="text-lg font-bold">
            Your library
          </h2>
          <label className="inline-flex items-center gap-2 text-[13px]" style={{ color: C.muted }}>
            Sort by
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as LibrarySort)}
              className={`h-9 rounded-full px-3 text-[13px] ${focusRing}`}
              style={{ background: "rgba(255,255,255,.05)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
            >
              {LIBRARY_SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center">
          <label className="relative block lg:w-[22rem]">
            <span className="sr-only">Search your papers</span>
            <MagnifyingGlass className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2" style={{ color: C.muted2 }} aria-hidden />
            <input
              type="search"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setShown(PAGE);
              }}
              placeholder="Title, author, venue, publisher or DOI"
              className={`h-10 w-full rounded-full pl-10 pr-4 text-[14px] ${focusRing}`}
              style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
            />
          </label>
          <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
            {LIBRARY_VIEWS.map((v) => {
              const on = view === v.value;
              return (
                <button
                  key={v.value}
                  type="button"
                  aria-pressed={on}
                  onClick={() => {
                    setView(v.value);
                    setShown(PAGE);
                  }}
                  className={`inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors ${focusRing}`}
                  style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.muted }}
                >
                  {v.label}
                  <span className="tabular-nums" style={{ opacity: on ? 0.75 : 0.7 }}>
                    {counts[v.value]}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="mt-5">
          {libraryQ.error ? (
            <div className="rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
              <InlineError
                message={
                  libraryQ.error instanceof ApiError
                    ? `Your library couldn't be loaded: ${libraryQ.error.message}.`
                    : "Your library couldn't be loaded: the server couldn't be reached."
                }
              />
              <button
                type="button"
                onClick={() => libraryQ.mutate()}
                className={`mt-4 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
                style={{ ...quietButton, color: C.ink }}
              >
                Try again
              </button>
            </div>
          ) : !libraryQ.data ? (
            <ul aria-label="Loading your library" className="overflow-hidden rounded-2xl" style={panel}>
              {[0, 1, 2, 3].map((i) => (
                <li key={i} className="border-b px-5 py-4 last:border-b-0" style={{ borderColor: C.line }}>
                  <div className="h-4 w-2/3 rounded motion-safe:animate-pulse" style={{ background: "rgba(150,175,230,.12)" }} />
                  <div className="mt-2.5 h-3 w-1/3 rounded motion-safe:animate-pulse" style={{ background: "rgba(150,175,230,.08)" }} />
                </li>
              ))}
            </ul>
          ) : entries.length === 0 ? (
            <div className="rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
              <p className="text-base font-semibold">No papers yet</p>
              <p className="mx-auto mt-2 max-w-[52ch] text-sm leading-relaxed" style={{ color: C.muted }}>
                Upload a PDF above. Papers you analyse, search from or add to a workspace are listed here too.
              </p>
            </div>
          ) : visible.length === 0 ? (
            <div className="rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
              <p className="text-sm" style={{ color: C.muted }}>
                No paper matches{query.trim() ? ` "${query.trim()}"` : ""} here.
              </p>
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setView("all");
                }}
                className={`mt-4 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
                style={{ ...quietButton, color: C.ink }}
              >
                Show every paper
              </button>
            </div>
          ) : (
            <>
              <p className="sr-only" aria-live="polite">
                {visible.length} paper{visible.length === 1 ? "" : "s"} shown
              </p>
              <ul aria-label="Your papers" className="overflow-hidden rounded-2xl" style={panel} data-testid="library">
                {visible.slice(0, shown).map((entry) => (
                  <LibraryRow key={entry.id} entry={entry} />
                ))}
              </ul>
              {visible.length > shown && (
                <div className="mt-4 flex justify-center">
                  <button
                    type="button"
                    onClick={() => setShown((n) => n + PAGE)}
                    className={`rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`}
                    style={{ ...quietButton, color: C.ink }}
                  >
                    Show {Math.min(PAGE, visible.length - shown)} more of {visible.length - shown}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </section>

      <OpenById />
    </PageShell>
  );
}

function LibraryRow({ entry }: { entry: LibraryEntry }) {
  const step = nextStep(entry);
  const byline = [authorLine(entry.authors), entry.venue, entry.publisher && entry.publisher !== entry.venue ? entry.publisher : null, entry.year]
    .filter(Boolean)
    .join(" · ");
  const roles = rolesLine(entry);
  return (
    <li className="border-b px-5 py-4 transition-colors last:border-b-0 hover:bg-white/[0.025]" style={{ borderColor: C.line }}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0">
          <Link
            href={`/papers/${entry.id}`}
            className={`rounded-sm text-[15px] font-semibold leading-snug hover:underline hover:decoration-[rgba(93,240,168,.5)] hover:underline-offset-4 ${focusRing}`}
          >
            {entry.title}
          </Link>
          <p className="mt-1 text-[13px] leading-snug" style={{ color: C.muted }}>
            {byline}
          </p>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]" style={{ color: C.muted }}>
            <span className="inline-flex items-center gap-1.5">
              <span className="size-1.5 rounded-full" style={{ background: COVERAGE_TONE[entry.coverage.state] }} aria-hidden />
              {COVERAGE_LABEL[entry.coverage.state]}
            </span>
            {entry.analyzed === true && (
              <span className="inline-flex items-center gap-1" style={{ color: C.mint }}>
                <CheckCircle className="size-3.5" weight="fill" aria-hidden />
                Research profile
              </span>
            )}
            {entry.analyzed === false && (
              <span className="inline-flex items-center gap-1">
                <CircleDashed className="size-3.5" aria-hidden />
                Not analysed
              </span>
            )}
            {roles && <span style={{ color: C.muted2 }}>{roles}</span>}
            <span style={{ color: C.muted2 }}>
              <Timestamp at={entry.last_active_at} />
            </span>
          </p>
          {entry.workspaces.length > 0 && (
            <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[12.5px]">
              <span style={{ color: C.muted2 }}>In</span>
              {entry.workspaces.map((w) => (
                <Link
                  key={w.workspace_id}
                  href={`/workspace/${w.workspace_id}`}
                  className={`rounded-full px-2.5 py-0.5 transition-colors hover:text-white ${focusRing}`}
                  style={{ border: `1px solid ${C.line}`, color: C.muted }}
                >
                  {w.title}
                </Link>
              ))}
            </p>
          )}
        </div>
        <Link
          href={step.href}
          className={`inline-flex shrink-0 items-center gap-1.5 self-start rounded-full px-4 py-2 text-[13px] font-semibold transition-colors hover:bg-white/10 ${focusRing}`}
          style={{ ...quietButton, color: C.ink }}
        >
          {step.label}
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </div>
    </li>
  );
}

function UploadPanel({ onUploaded }: { onUploaded: (paperId: string) => void }) {
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const polling = useJobPolling(state.phase === "reading" ? state.jobId : null);

  // the read finished: open the paper, or say why it couldn't be read
  const readFailed = state.phase === "reading" && polling.isDone && polling.job?.status !== "succeeded";
  useEffect(() => {
    if (state.phase === "reading" && polling.isDone && polling.job?.status === "succeeded") onUploaded(state.paperId);
  }, [state, polling.isDone, polling.job, onUploaded]);
  const failure = readFailed
    ? polling.job?.error
      ? `The PDF couldn't be read: ${polling.job.error}`
      : "The PDF couldn't be read. Try uploading it again."
    : state.phase === "error"
      ? state.message
      : null;

  const handleFile = useCallback(
    async (file: File) => {
      const refused = checkPdfFile(file);
      if (refused) {
        setState({ phase: "error", message: refused === "Not a PDF file." ? "Only PDF files can be read." : `This file is ${refused.toLowerCase()}` });
        return;
      }
      setState({ phase: "uploading", name: file.name });
      try {
        const res = await papersApi.upload(file);
        recordRecentPaper({ paperId: res.paper_id, title: file.name.replace(/\.pdf$/i, ""), addedAt: new Date().toISOString() });
        if (res.deduplicated || !res.job) {
          onUploaded(res.paper_id); // already read once: the same paper
          return;
        }
        setState({ phase: "reading", name: file.name, paperId: res.paper_id, jobId: res.job.job_id });
      } catch (err) {
        setState({ phase: "error", message: uploadErrorMessage(err) });
      }
    },
    [onUploaded],
  );

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  }

  const busy = state.phase === "uploading" || (state.phase === "reading" && !readFailed);
  const progress = polling.job?.progress as Record<string, unknown> | undefined;
  const step =
    state.phase === "uploading"
      ? "Uploading"
      : state.phase === "reading" && !readFailed
        ? progress?.metadata === "running"
          ? "Completing its record from Crossref, OpenAlex, Semantic Scholar and arXiv"
          : "Reading the PDF: sections, abstract, references"
        : null;

  return (
    <section aria-label="Upload a paper" className="mt-8">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        data-testid="upload-drop"
        className="flex flex-col gap-5 rounded-2xl px-6 py-6 transition-colors sm:flex-row sm:items-center sm:justify-between"
        style={{
          background: dragActive ? "rgba(93,240,168,.07)" : C.glass,
          border: `1px dashed ${dragActive ? "rgba(93,240,168,.55)" : C.lineStrong}`,
        }}
      >
        <div className="flex items-start gap-4">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl" style={{ background: "rgba(93,240,168,.08)", border: "1px solid rgba(93,240,168,.22)" }}>
            <FilePdf className="size-5" style={{ color: C.mint }} aria-hidden />
          </span>
          <div>
            <p className="text-[15px] font-semibold">{dragActive ? "Drop it to read it" : "Drop a PDF here, or choose one"}</p>
            <p className="mt-1 max-w-[60ch] text-[13px] leading-relaxed" style={{ color: C.muted }}>
              Any research paper with a text layer, up to {MAX_PDF_MB} MB and {MAX_PDF_PAGES} pages. Its sections, abstract and references are read,
              and its record is completed from the scholarly sources.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold transition-[opacity,transform] active:scale-[0.97] disabled:opacity-60 ${focusRing}`}
          style={primaryButton}
        >
          <UploadSimple className="size-4" aria-hidden />
          {busy ? "Reading…" : "Browse for a file"}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          data-testid="upload-input"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFile(file);
            e.target.value = "";
          }}
        />
      </div>
      <div className="mt-3 min-h-6" aria-live="polite">
        {step && (
          <p role="status" className="flex items-center gap-2 text-[13.5px]" style={{ color: C.muted }}>
            <span className="size-2 rounded-full motion-safe:animate-pulse" style={{ background: C.mint }} aria-hidden />
            <span className="font-medium" style={{ color: C.ink }}>
              {state.phase !== "idle" && state.phase !== "error" ? state.name : ""}
            </span>
            {step}…
          </p>
        )}
        {failure && <InlineError message={failure} />}
      </div>
    </section>
  );
}

function OpenById() {
  const router = useRouter();
  const [id, setId] = useState("");
  return (
    <form
      className="mt-12 flex flex-wrap items-center gap-2 border-t pt-6 text-[13px]"
      style={{ borderColor: C.line }}
      onSubmit={(e) => {
        e.preventDefault();
        if (id.trim()) router.push(`/papers/${encodeURIComponent(id.trim())}`);
      }}
    >
      <label htmlFor="jump-id" style={{ color: C.muted }}>
        Have a paper ID?
      </label>
      <input
        id="jump-id"
        value={id}
        onChange={(e) => setId(e.target.value)}
        placeholder="pap_…"
        spellCheck={false}
        className={`h-9 w-56 rounded-full px-3.5 font-mono text-[13px] ${focusRing}`}
        style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
      />
      <button type="submit" className={`h-9 rounded-full px-4 font-semibold transition-colors hover:bg-white/10 ${focusRing}`} style={{ ...quietButton, color: C.ink }}>
        Open
      </button>
    </form>
  );
}
