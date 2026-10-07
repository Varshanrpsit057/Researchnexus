"use client";

import { useState, type FormEvent } from "react";
import { NotePencil, PushPin } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { WorkspacePaper } from "@/lib/api/types";
import { parseTags } from "@/lib/workspace-overview";
import { C, InlineError, focusRing, primaryButton, quietButton } from "@/components/cinematic/ui";

/** A workspace paper's own annotations: pinned to the top of the list, tags
 * and a note -- the reader's, never generated (they moved here from the old
 * workspace Papers tab, 2026-10-06). */
export function PaperAnnotations({
  workspaceId,
  paper,
  title,
  onSaved,
}: {
  workspaceId: string;
  paper: WorkspacePaper;
  title: string;
  onSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tags, setTags] = useState(paper.tags.join(", "));
  const [note, setNote] = useState(paper.note ?? "");

  async function save(body: Parameters<typeof workspaces.updatePaper>[2]): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await workspaces.updatePaper(workspaceId, paper.paper_id, body);
      await onSaved();
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? `Not saved: ${err.message}.` : "Not saved: the server couldn't be reached.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await save({ tags: parseTags(tags), note: note.trim() || null })) setEditing(false);
  }

  return (
    <div className="mt-2">
      {paper.tags.length > 0 && !editing && (
        <ul aria-label="Tags" className="mb-2 flex flex-wrap gap-1.5">
          {paper.tags.map((t) => (
            <li key={t} className="rounded-full px-2.5 py-0.5 text-[12px]" style={{ border: `1px solid ${C.line}`, color: C.muted }}>
              {t}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-1">
        <button
          type="button"
          onClick={() => save({ pinned: !paper.pinned })}
          disabled={busy}
          aria-pressed={paper.pinned}
          aria-label={paper.pinned ? `Unpin ${title}` : `Pin ${title} to the top`}
          className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-2.5 text-[12.5px] transition-colors hover:bg-white/10 hover:text-white disabled:opacity-60 sm:min-h-8 ${focusRing}`}
          style={{ color: paper.pinned ? C.mint : C.muted }}
        >
          <PushPin className="size-3.5" weight={paper.pinned ? "fill" : "regular"} aria-hidden />
          {paper.pinned ? "Pinned" : "Pin"}
        </button>
        {!editing && (
          <button
            type="button"
            onClick={() => {
              setTags(paper.tags.join(", "));
              setNote(paper.note ?? "");
              setEditing(true);
            }}
            aria-label={`${paper.tags.length || paper.note ? "Edit" : "Add"} tags and a note for ${title}`}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-2.5 text-[12.5px] transition-colors hover:bg-white/10 hover:text-white sm:min-h-8 ${focusRing}`}
            style={{ color: C.muted }}
          >
            <NotePencil className="size-3.5" aria-hidden />
            {paper.tags.length || paper.note ? "Edit tags and note" : "Add tags or a note"}
          </button>
        )}
      </div>
      {editing && (
        <form onSubmit={submit} aria-label={`Tags and note for ${title}`} className="mt-2 grid max-w-xl gap-3 rounded-xl p-3" style={{ border: `1px solid ${C.line}`, background: "rgba(255,255,255,.02)" }}>
          <label className="block">
            <span className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
              Tags <span className="font-normal">(separated by commas)</span>
            </span>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="baseline, dataset, to cite"
              autoFocus
              className={`mt-1 h-10 w-full rounded-xl px-3 text-[14px] ${focusRing}`}
              style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
            />
          </label>
          <label className="block">
            <span className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
              Note
            </span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              maxLength={4000}
              placeholder="Why it matters to your research"
              className={`mt-1 w-full resize-y rounded-xl px-3 py-2 text-[14px] leading-relaxed ${focusRing}`}
              style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
            />
          </label>
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className={`rounded-full px-4 py-2 text-sm font-semibold disabled:opacity-60 ${focusRing}`} style={primaryButton}>
              {busy ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className={`rounded-full px-4 py-2 text-sm font-semibold hover:bg-white/10 ${focusRing}`}
              style={{ ...quietButton, color: C.ink }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && (
        <div className="mt-2">
          <InlineError message={error} />
        </div>
      )}
    </div>
  );
}
