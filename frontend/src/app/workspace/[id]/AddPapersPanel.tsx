"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore, type DragEvent, type FormEvent, type ReactNode } from "react";
import useSWR from "swr";
import { ArrowClockwise, CheckCircle, CircleNotch, FilePdf, UploadSimple, WarningCircle, X } from "@phosphor-icons/react/dist/ssr";
import { jobs, papers as papersApi, workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { recordRecentPaper, useRecentPapers } from "@/lib/local-history";
import { MAX_PDF_MB, MAX_PDF_PAGES, checkPdfFile, ingestPdf, parsePaperIds } from "@/lib/paper-upload";
import { BUSY_STATUSES, addErrorMessage, createUploadQueue, type UploadItem, type UploadStatus } from "@/lib/upload-queue";
import { addableFromRun } from "@/lib/workspace-overview";
import type { Workspace } from "@/lib/api/types";
import { C, InlineError, focusRing, panel, primaryButton, quietButton } from "./ui";

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function AddPapersPanel({ workspace, onAdded }: { workspace: Workspace; onAdded: () => Promise<void> }) {
  const members = new Set(workspace.papers.map((p) => p.paper_id));
  return (
    <div className="mb-4 divide-y rounded-2xl" style={{ ...panel, border: `1px solid ${C.lineStrong}` }}>
      <UploadPdfs workspaceId={workspace.workspace_id} onAdded={onAdded} />
      {workspace.source_run_id && <RunPicks workspace={workspace} onAdded={onAdded} />}
      <RecentPicks workspaceId={workspace.workspace_id} members={members} onAdded={onAdded} />
      <AddById workspaceId={workspace.workspace_id} members={members} onAdded={onAdded} />
    </div>
  );
}

function Section({ children }: { children: ReactNode }) {
  return (
    <div className="p-5" style={{ borderColor: C.line }}>
      {children}
    </div>
  );
}

// --- upload PDFs ------------------------------------------------------

function UploadPdfs({ workspaceId, onAdded }: { workspaceId: string; onAdded: () => Promise<void> }) {
  const [queue] = useState(() =>
    createUploadQueue({
      ingest: (file, onParsing) => ingestPdf(file, { upload: papersApi.upload, getJob: jobs.get, onParsing }),
      addToWorkspace: async (ids) => (await workspaces.addPapers(workspaceId, { paper_ids: ids })).added,
      onUploaded: (paperId, file) =>
        recordRecentPaper({ paperId, title: file.name.replace(/\.pdf$/i, ""), addedAt: new Date().toISOString() }),
    }),
  );
  // the page passes a fresh callback each render; the queue outlives renders
  useEffect(() => queue.setOnAdded(onAdded), [queue, onAdded]);
  const items = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const headingId = useId();

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files?.length) queue.add(e.dataTransfer.files);
  }

  const busy = items.filter((it) => BUSY_STATUSES.includes(it.status)).length;
  const done = items.filter((it) => it.status === "added").length;
  const finished = items.some((it) => !BUSY_STATUSES.includes(it.status));

  return (
    <Section>
      <h3 id={headingId} className="text-sm font-semibold">
        Upload PDFs
      </h3>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        data-active={dragActive || undefined}
        className="mt-3 flex flex-col items-center gap-3 rounded-xl border border-dashed px-5 py-7 text-center transition-colors data-[active]:border-[#5df0a8] data-[active]:bg-[rgba(93,240,168,0.06)] sm:flex-row sm:text-left"
        style={{ borderColor: dragActive ? undefined : C.lineStrong }}
      >
        <UploadSimple className="size-6 shrink-0" style={{ color: C.mint }} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">Drop PDFs here to add them to this workspace</p>
          <p className="mt-0.5 text-[13px]" style={{ color: C.muted }}>
            Several at once is fine. PDF only, up to {MAX_PDF_MB} MB and {MAX_PDF_PAGES} pages each.
          </p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className={`inline-flex min-h-11 shrink-0 items-center rounded-full px-4 py-2 text-sm font-semibold sm:min-h-0 ${focusRing}`}
          style={primaryButton}
        >
          Choose PDFs
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) queue.add(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      <p className="sr-only" aria-live="polite">
        {busy > 0 ? `Uploading ${plural(busy, "file")}.` : done > 0 ? `${plural(done, "paper")} added.` : ""}
      </p>

      {items.length > 0 && (
        <>
          <ul className="mt-3 space-y-1" aria-labelledby={headingId}>
            {items.map((it) => (
              <UploadRow key={it.key} item={it} onRetry={() => queue.retry(it.key)} onDismiss={() => queue.dismiss(it.key)} />
            ))}
          </ul>
          {finished && (
            <button
              type="button"
              onClick={() => queue.clearFinished()}
              className={`mt-2 rounded-sm text-sm font-medium underline underline-offset-4 hover:text-white ${focusRing}`}
              style={{ color: C.muted }}
            >
              Clear finished
            </button>
          )}
        </>
      )}
    </Section>
  );
}

const STATUS_TEXT: Partial<Record<UploadStatus, string>> = {
  queued: "Waiting",
  uploading: "Uploading…",
  parsing: "Reading the PDF…",
  adding: "Adding to the workspace…",
  added: "Added",
  already: "Already in this workspace",
};

function UploadRow({ item, onRetry, onDismiss }: { item: UploadItem; onRetry: () => void; onDismiss: () => void }) {
  const spinning = item.status === "uploading" || item.status === "parsing" || item.status === "adding";
  const failed = item.status === "failed";
  const ok = item.status === "added" || item.status === "already";
  const canRetry = failed && (item.paperId !== undefined || checkPdfFile(item.file) === null);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2.5" style={{ background: "rgba(255,255,255,.03)" }}>
      <FilePdf className="size-5 shrink-0" style={{ color: C.muted }} aria-hidden />
      {/* the min width pushes the status onto its own line on narrow screens
          instead of squeezing the file name down to a few characters */}
      <span className="min-w-[10rem] flex-1 truncate text-sm font-medium" title={item.file.name}>
        {item.file.name}
      </span>
      <span
        className="inline-flex items-center gap-1.5 text-[13px]"
        style={{ color: failed ? C.danger : ok ? C.mint : C.muted }}
      >
        {spinning && <CircleNotch className="size-4 motion-safe:animate-spin" aria-hidden />}
        {ok && <CheckCircle className="size-4" weight="fill" aria-hidden />}
        {failed && <WarningCircle className="size-4" weight="bold" aria-hidden />}
        {failed ? item.message : STATUS_TEXT[item.status]}
      </span>
      {failed && (
        <span className="flex items-center gap-1">
          {canRetry && (
            <button
              type="button"
              onClick={onRetry}
              aria-label={`Retry ${item.file.name}`}
              className={`inline-flex min-h-11 items-center gap-1 rounded-full px-3 text-sm font-semibold hover:bg-white/10 sm:min-h-8 ${focusRing}`}
            >
              <ArrowClockwise className="size-3.5" weight="bold" aria-hidden />
              Retry
            </button>
          )}
          <button
            type="button"
            onClick={onDismiss}
            aria-label={`Dismiss ${item.file.name}`}
            className={`inline-flex size-11 items-center justify-center rounded-full hover:bg-white/10 sm:size-8 ${focusRing}`}
            style={{ color: C.muted }}
          >
            <X className="size-4" weight="bold" aria-hidden />
          </button>
        </span>
      )}
    </li>
  );
}

// --- pick lists: discovery run results and recent uploads -------------

interface PickItem {
  id: string;
  title: string;
  meta?: string;
}

function PickList({
  title,
  note,
  items,
  onAdd,
}: {
  title: string;
  note?: string;
  items: PickItem[];
  onAdd: (ids: string[]) => Promise<void>;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const headingId = useId();

  // items leave the list once they're in the workspace; drop them from the selection too
  const visible = new Set(items.map((i) => i.id));
  const chosen = selected.filter((id) => visible.has(id));
  const allChosen = items.length > 0 && chosen.length === items.length;

  function toggle(id: string) {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  }

  async function add() {
    if (chosen.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(chosen);
      setSelected([]);
      // the rows just added are gone; keep focus in this list
      headingRef.current?.focus();
    } catch (err) {
      setError(addErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-sm font-semibold outline-none">
          {title}
        </h3>
        {items.length > 1 && (
          <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 text-[13px] sm:min-h-0" style={{ color: C.muted }}>
            <input
              type="checkbox"
              checked={allChosen}
              onChange={() => setSelected(allChosen ? [] : items.map((i) => i.id))}
              className="size-4 accent-[#5df0a8]"
            />
            Select all
          </label>
        )}
      </div>
      {note && (
        <p className="mt-1 text-[13px]" style={{ color: C.muted }}>
          {note}
        </p>
      )}
      <ul className="mt-2 space-y-0.5" aria-labelledby={headingId}>
        {items.map((it) => (
          <li key={it.id}>
            <label className="flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-white/[0.04]">
              <input
                type="checkbox"
                checked={chosen.includes(it.id)}
                onChange={() => toggle(it.id)}
                className="mt-0.5 size-4 shrink-0 accent-[#5df0a8]"
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium leading-snug">{it.title}</span>
                {it.meta && (
                  <span className="mt-0.5 block text-[13px] tabular-nums" style={{ color: C.muted }}>
                    {it.meta}
                  </span>
                )}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={add}
          disabled={busy || chosen.length === 0}
          className={`inline-flex min-h-11 items-center rounded-full px-4 py-2 text-sm font-semibold disabled:opacity-50 sm:min-h-0 ${focusRing}`}
          style={primaryButton}
        >
          {busy ? "Adding…" : chosen.length > 0 ? `Add ${plural(chosen.length, "paper")}` : "Select papers to add"}
        </button>
        {error && <InlineError message={error} />}
      </div>
    </Section>
  );
}

function RunPicks({ workspace, onAdded }: { workspace: Workspace; onAdded: () => Promise<void> }) {
  const runId = workspace.source_run_id as string;
  const related = useSWR(["related", workspace.seed_paper_id, runId], () => papersApi.related(workspace.seed_paper_id, runId));

  if (related.isLoading) {
    return (
      <Section>
        <div role="status" className="space-y-2">
          <span className="sr-only">Loading discovery results…</span>
          <div className="h-12 motion-safe:animate-pulse rounded-xl" style={{ background: "rgba(255,255,255,.05)" }} />
          <div className="h-12 motion-safe:animate-pulse rounded-xl" style={{ background: "rgba(255,255,255,.05)" }} />
        </div>
      </Section>
    );
  }
  if (related.error) {
    return (
      <Section>
        <InlineError message="Could not load this workspace's discovery results. Close this panel and try again." />
      </Section>
    );
  }
  const addable = related.data ? addableFromRun(related.data.results, workspace.papers) : [];
  if (addable.length === 0) {
    return (
      <Section>
        <h3 className="text-sm font-semibold">From this workspace&apos;s discovery run</h3>
        <p className="mt-1 text-sm" style={{ color: C.muted }}>
          Every paper from the discovery run is already in this workspace.
        </p>
      </Section>
    );
  }
  return (
    <PickList
      title="From this workspace's discovery run"
      items={addable.map((r) => ({
        id: r.paper.id,
        title: r.paper.title,
        meta: [
          r.final_rank != null ? `#${r.final_rank}` : null,
          r.band ? `${r.band} confidence` : null,
          r.paper.year != null ? String(r.paper.year) : null,
          r.paper.authors[0] ? `${r.paper.authors[0]}${r.paper.authors.length > 1 ? " et al." : ""}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      }))}
      onAdd={async (ids) => {
        await workspaces.addPapers(workspace.workspace_id, { paper_ids: ids, from_run_id: runId });
        await onAdded();
      }}
    />
  );
}

function RecentPicks({ workspaceId, members, onAdded }: { workspaceId: string; members: Set<string>; onAdded: () => Promise<void> }) {
  const recent = useRecentPapers().filter((p) => !members.has(p.paperId));
  if (recent.length === 0) return null;
  return (
    <PickList
      title="Your recent uploads"
      note="Papers uploaded from this browser that aren't in this workspace yet."
      items={recent.map((p) => ({ id: p.paperId, title: p.title }))}
      onAdd={async (ids) => {
        await workspaces.addPapers(workspaceId, { paper_ids: ids });
        await onAdded();
      }}
    />
  );
}

// --- add by id ----------------------------------------------------------

function AddById({ workspaceId, members, onAdded }: { workspaceId: string; members: Set<string>; onAdded: () => Promise<void> }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const inputId = useId();
  const hintId = useId();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ids = parsePaperIds(value);
    if (ids.length === 0) return;
    setBusy(true);
    setResult(null);
    const fresh = ids.filter((id) => !members.has(id));
    const already = ids.length - fresh.length;
    try {
      // check every id first: the add request is all-or-nothing, so one
      // mistyped id would otherwise block the rest
      const checks = await Promise.allSettled(fresh.map((id) => papersApi.get(id)));
      const missing = fresh.filter((_, i) => {
        const c = checks[i];
        return c.status === "rejected" && c.reason instanceof ApiError && c.reason.status === 404;
      });
      const unreachable = checks.some((c) => c.status === "rejected" && !(c.reason instanceof ApiError && c.reason.status === 404));
      if (unreachable) throw new TypeError("paper lookup failed");
      const found = fresh.filter((id) => !missing.includes(id));
      if (found.length > 0) {
        await workspaces.addPapers(workspaceId, { paper_ids: found });
        await onAdded();
      }
      const parts = [
        found.length > 0 ? `Added ${plural(found.length, "paper")}.` : null,
        already > 0 ? `${plural(already, "paper")} already in this workspace.` : null,
        missing.length > 0 ? `No paper found for ${missing.join(", ")}. Upload ${missing.length === 1 ? "it" : "them"} first.` : null,
      ].filter(Boolean);
      // keep only the ids that still need attention in the box
      setValue(missing.join(", "));
      setResult({ tone: missing.length > 0 ? "error" : "ok", text: parts.join(" ") });
    } catch (err) {
      setResult({ tone: "error", text: addErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section>
      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <label htmlFor={inputId} className="mb-1.5 block text-sm font-semibold">
            Add by paper ID
          </label>
          <input
            id={inputId}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="pap_…, pap_…"
            autoComplete="off"
            spellCheck={false}
            aria-describedby={hintId}
            className="h-11 w-full rounded-xl px-3 font-mono text-sm caret-[#5df0a8] outline-none transition-colors placeholder:text-[#8f9bb8] focus-visible:border-[#5df0a8] sm:h-10"
            style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
          />
        </div>
        <button
          type="submit"
          disabled={busy || parsePaperIds(value).length === 0}
          className={`h-11 shrink-0 rounded-full px-5 text-sm font-semibold transition-colors hover:bg-white/10 disabled:opacity-50 sm:h-10 ${focusRing}`}
          style={quietButton}
        >
          {busy ? "Adding…" : "Add"}
        </button>
      </form>
      <p id={hintId} className="mt-1.5 text-[13px]" style={{ color: C.muted }}>
        Separate several IDs with commas or spaces.
      </p>
      {result &&
        (result.tone === "error" ? (
          <div className="mt-2">
            <InlineError message={result.text} />
          </div>
        ) : (
          <p role="status" className="mt-2 flex items-center gap-1.5 text-sm" style={{ color: C.mint }}>
            <CheckCircle className="size-4" weight="fill" aria-hidden />
            {result.text}
          </p>
        ))}
    </Section>
  );
}
