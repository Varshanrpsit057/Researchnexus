"use client";

import { useState, type FormEvent } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { PushPin, PushPinSlash, Trash, X } from "@phosphor-icons/react/dist/ssr";
import { useWorkspace } from "../layout";
import { workspaces } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { WorkspacePaper } from "@/lib/api/types";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge, ConfidenceBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/States";

export default function WorkspacePapersPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { data: workspace, mutate } = useWorkspace(workspaceId);
  const [addId, setAddId] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  if (!workspace) return null;

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    const paperId = addId.trim();
    if (!paperId) return;
    setAdding(true);
    setAddError(null);
    try {
      await workspaces.addPapers(workspaceId, { paper_ids: [paperId] });
      setAddId("");
      await mutate();
    } catch (err) {
      setAddError(err instanceof ApiError ? err.message : "Could not add that paper.");
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="space-y-6">
      <ul className="space-y-3">
        {workspace.papers.map((p) => (
          <PaperRow key={p.paper_id} workspaceId={workspaceId} paper={p} onChanged={() => mutate()} />
        ))}
      </ul>

      <Card>
        <CardBody>
          <form onSubmit={handleAdd} className="flex items-end gap-2">
            <div className="flex-1">
              <label htmlFor="add-paper-id" className="mb-1.5 block text-sm font-medium text-ink">
                Add a paper by ID
              </label>
              <input
                id="add-paper-id"
                value={addId}
                onChange={(e) => setAddId(e.target.value)}
                placeholder="pap_..."
                className="h-10 w-full rounded-sm border border-border-strong bg-surface-raised px-3 font-mono text-sm text-ink placeholder:text-ink-subtle focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
              />
            </div>
            <Button type="submit" variant="secondary" loading={adding}>
              Add
            </Button>
          </form>
          {addError && (
            <div className="mt-2">
              <InlineError message={addError} />
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function PaperRow({
  workspaceId,
  paper,
  onChanged,
}: {
  workspaceId: string;
  paper: WorkspacePaper;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [tags, setTags] = useState(paper.tags.join(", "));
  const [note, setNote] = useState(paper.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function togglePin() {
    setBusy(true);
    setError(null);
    try {
      await workspaces.updatePaper(workspaceId, paper.paper_id, { pinned: !paper.pinned });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update.");
    } finally {
      setBusy(false);
    }
  }

  async function saveEdits() {
    setBusy(true);
    setError(null);
    try {
      await workspaces.updatePaper(workspaceId, paper.paper_id, {
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        note: note.trim() || null,
      });
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await workspaces.removePaper(workspaceId, paper.paper_id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove this paper.");
      setBusy(false);
    }
  }

  return (
    <li>
      <Card>
        <CardBody className="space-y-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Link href={`/papers/${paper.paper_id}`} className="truncate text-sm font-medium text-ink hover:underline">
                {paper.paper_id}
              </Link>
              <p className="mt-0.5 text-xs text-ink-subtle">
                {paper.role} · {paper.grounding.replace("_", " ")} · added {paper.added_by}
              </p>
              {paper.ranking_snapshot && (
                <div className="mt-1">
                  <ConfidenceBadge confidence={paper.ranking_snapshot.band} />
                </div>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={togglePin}
                disabled={busy}
                aria-pressed={paper.pinned}
                aria-label={paper.pinned ? "Unpin paper" : "Pin paper"}
                className="rounded-sm p-1.5 text-ink-muted hover:bg-surface-sunken hover:text-ink disabled:opacity-50"
              >
                {paper.pinned ? <PushPin className="size-4" weight="fill" aria-hidden /> : <PushPinSlash className="size-4" aria-hidden />}
              </button>
              {paper.role !== "seed" && (
                <button
                  type="button"
                  onClick={remove}
                  disabled={busy}
                  aria-label="Remove paper from workspace"
                  className="rounded-sm p-1.5 text-ink-muted hover:bg-danger-wash hover:text-danger disabled:opacity-50"
                >
                  <Trash className="size-4" aria-hidden />
                </button>
              )}
            </div>
          </div>

          {paper.tags.length > 0 && !editing && (
            <div className="flex flex-wrap gap-1">
              {paper.tags.map((t) => (
                <Badge key={t}>{t}</Badge>
              ))}
            </div>
          )}
          {paper.note && !editing && <p className="text-sm text-ink-muted">{paper.note}</p>}

          {editing ? (
            <div className="rule-t space-y-2 pt-2">
              <input
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="tags, comma, separated"
                className="h-9 w-full rounded-sm border border-border-strong bg-surface-raised px-3 text-sm text-ink placeholder:text-ink-subtle focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
              />
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Note"
                rows={2}
                className="w-full rounded-sm border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink placeholder:text-ink-subtle focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
              />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                  <X className="size-3.5" aria-hidden />
                  Cancel
                </Button>
                <Button size="sm" onClick={saveEdits} loading={busy}>
                  Save
                </Button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setEditing(true)} className="text-xs text-ink-subtle hover:text-ink-muted">
              Edit tags / note
            </button>
          )}
          {error && <InlineError message={error} />}
        </CardBody>
      </Card>
    </li>
  );
}
