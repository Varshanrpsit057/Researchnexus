"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import useSWR, { useSWRConfig } from "swr";
import { ArrowRight, PencilSimple } from "@phosphor-icons/react/dist/ssr";
import { workspaces as workspacesApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { Workspace } from "@/lib/api/types";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { parseTimestamp } from "@/lib/time";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { DeleteWorkspaceButton } from "@/components/workspaces/DeleteWorkspace";
import { Timestamp } from "@/components/ui/Timestamp";
import { C, InlineError, focusRing, panel, primaryButton, quietButton } from "@/components/cinematic/ui";

export default function WorkspacesPage() {
  const { ready } = useRequireAuth();
  const listQ = useSWR(ready ? "workspaces" : null, () => workspacesApi.list());
  const [announcement, setAnnouncement] = useState("");

  if (!ready) return null;
  const list = [...(listQ.data?.workspaces ?? [])].sort(
    (a, b) => parseTimestamp(b.updated_at).getTime() - parseTimestamp(a.updated_at).getTime(),
  );

  return (
    <PageShell>
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b pb-6" style={{ borderColor: C.lineStrong }}>
        <div>
          <h1 className="text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Workspaces</h1>
          <p className="mt-3 max-w-[64ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
            A workspace holds a seed paper and the related work you keep, with its research trail, graph, chat, comparisons, gaps and
            directions.
          </p>
        </div>
        <Link href="/papers" className={`inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
          Start from a paper
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      </header>

      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>

      <div className="mt-8">
        {listQ.error ? (
          <div className="rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <InlineError
              message={listQ.error instanceof ApiError ? `Your workspaces couldn't be loaded: ${listQ.error.message}.` : "Your workspaces couldn't be loaded: the server couldn't be reached."}
            />
            <button type="button" onClick={() => listQ.mutate()} className={`mt-4 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={{ ...quietButton, color: C.ink }}>
              Try again
            </button>
          </div>
        ) : !listQ.data ? (
          <ul aria-label="Loading your workspaces" className="overflow-hidden rounded-2xl" style={panel}>
            {[0, 1].map((i) => (
              <li key={i} className="border-b px-6 py-5 last:border-b-0" style={{ borderColor: C.line }}>
                <div className="h-5 w-1/3 rounded motion-safe:animate-pulse" style={{ background: "rgba(150,175,230,.12)" }} />
                <div className="mt-3 h-3 w-1/2 rounded motion-safe:animate-pulse" style={{ background: "rgba(150,175,230,.08)" }} />
              </li>
            ))}
          </ul>
        ) : list.length === 0 ? (
          <div className="rounded-2xl px-6 py-14 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <p className="text-base font-semibold">No workspaces yet</p>
            <p className="mx-auto mt-2 max-w-[56ch] text-sm leading-relaxed" style={{ color: C.muted }}>
              Open a paper and analyse it, then either discover related work and keep the results you want, or start a workspace with just
              that paper and add your own.
            </p>
            <Link href="/papers" className={`mt-6 inline-flex rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
              Choose a paper
            </Link>
          </div>
        ) : (
          <ul aria-label="Your workspaces" className="overflow-hidden rounded-2xl" style={panel}>
            {list.map((ws) => (
              <WorkspaceListRow key={ws.workspace_id} ws={ws} onChanged={setAnnouncement} />
            ))}
          </ul>
        )}
      </div>
    </PageShell>
  );
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

function WorkspaceListRow({ ws, onChanged }: { ws: Workspace; onChanged: (text: string) => void }) {
  const { mutate } = useSWRConfig();
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(ws.title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const counts = ws.counts;
  const papers = counts?.papers ?? ws.papers.length;
  const fullText = ws.papers.filter((p) => p.grounding === "full_text").length;

  async function rename(e: FormEvent) {
    e.preventDefault();
    const next = title.trim();
    if (!next || next === ws.title) {
      setRenaming(false);
      setTitle(ws.title);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await workspacesApi.update(ws.workspace_id, { title: next });
      await mutate("workspaces");
      void mutate(["workspace", ws.workspace_id]);
      setRenaming(false);
      onChanged(`Renamed to ${next}.`);
    } catch (err) {
      setError(err instanceof ApiError ? `Not renamed: ${err.message}.` : "Not renamed: the server couldn't be reached.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="border-b px-6 py-5 last:border-b-0" style={{ borderColor: C.line }} data-testid={`workspace-row-${ws.workspace_id}`}>
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between md:gap-8">
        <div className="min-w-0 flex-1">
          {renaming ? (
            <form onSubmit={rename} className="flex flex-wrap items-center gap-2">
              <label className="min-w-0 flex-1">
                <span className="sr-only">Workspace name</span>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={200}
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      setRenaming(false);
                      setTitle(ws.title);
                    }
                  }}
                  className={`h-10 w-full rounded-xl px-3 text-[16px] font-semibold ${focusRing}`}
                  style={{ background: "rgba(255,255,255,.05)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
                />
              </label>
              <button type="submit" disabled={busy || !title.trim()} className={`h-10 rounded-full px-4 text-sm font-semibold disabled:opacity-50 ${focusRing}`} style={primaryButton}>
                {busy ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setRenaming(false);
                  setTitle(ws.title);
                }}
                className={`h-10 rounded-full px-4 text-sm font-semibold hover:bg-white/10 ${focusRing}`}
                style={{ ...quietButton, color: C.ink }}
              >
                Cancel
              </button>
            </form>
          ) : (
            <Link
              href={`/workspace/${ws.workspace_id}`}
              className={`rounded-sm text-[18px] font-bold leading-snug tracking-[-0.01em] hover:underline hover:decoration-[rgba(93,240,168,.5)] hover:underline-offset-4 ${focusRing}`}
            >
              {ws.title}
            </Link>
          )}
          {ws.seed_title && (
            <p className="mt-1.5 text-[13.5px] leading-snug" style={{ color: C.muted }}>
              Seeded from{" "}
              <Link href={`/papers/${ws.seed_paper_id}`} className={`rounded-sm hover:text-white hover:underline hover:underline-offset-4 ${focusRing}`} style={{ color: C.ink }}>
                {ws.seed_title}
              </Link>
            </p>
          )}
          <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[13px] tabular-nums" style={{ color: C.muted }}>
            <span>
              {plural(papers, "paper")}
              {papers > 0 && <span style={{ color: C.muted2 }}> ({fullText} full text)</span>}
            </span>
            {counts && (
              <>
                <span>{plural(counts.edges, "connection")}</span>
                <span>{plural(counts.comparisons, "comparison")}</span>
                <span>{plural(counts.gaps, "gap")}</span>
                <span>{plural(counts.directions, "direction")}</span>
              </>
            )}
            <span style={{ color: C.muted2 }}>
              updated <Timestamp at={ws.updated_at} />
            </span>
          </p>
          {error && (
            <div className="mt-3">
              <InlineError message={error} />
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {!renaming && (
            <>
              <button
                type="button"
                onClick={() => setRenaming(true)}
                aria-label={`Rename ${ws.title}`}
                className={`grid size-9 place-items-center rounded-full transition-colors hover:bg-white/10 hover:text-white ${focusRing}`}
                style={{ color: C.muted }}
              >
                <PencilSimple className="size-4" aria-hidden />
              </button>
              <DeleteWorkspaceButton ws={ws} onDeleted={(t) => onChanged(`${t} deleted.`)} onError={setError} />
            </>
          )}
          <Link
            href={`/workspace/${ws.workspace_id}`}
            className={`ml-1 inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-[13px] font-semibold transition-colors hover:bg-white/10 ${focusRing}`}
            style={{ ...quietButton, color: C.ink }}
          >
            Open
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      </div>

    </li>
  );
}
