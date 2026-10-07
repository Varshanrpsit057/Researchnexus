"use client";

import { useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { Trash } from "@phosphor-icons/react/dist/ssr";
import { workspaces as workspacesApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { Workspace } from "@/lib/api/types";
import { CinematicDialog, type CinematicDialogHandle } from "@/components/ui/CinematicDialog";
import { C, focusRing, quietButton } from "@/components/cinematic/ui";

/** Deleting a workspace, behind a confirmation that says exactly what goes
 * (its trail and review, chats, comparisons, gaps, directions) and what
 * stays (its papers) -- one component for every page that offers it. */
export function DeleteWorkspaceButton({
  ws,
  variant = "icon",
  onDeleted,
  onError,
}: {
  ws: Workspace;
  variant?: "icon" | "text";
  onDeleted: (title: string) => void;
  onError: (message: string) => void;
}) {
  const { mutate } = useSWRConfig();
  const dialog = useRef<CinematicDialogHandle>(null);
  const [busy, setBusy] = useState(false);
  const papers = ws.counts?.papers ?? ws.papers.length;

  async function remove() {
    setBusy(true);
    try {
      await workspacesApi.remove(ws.workspace_id);
      dialog.current?.close();
      onDeleted(ws.title);
      await mutate("workspaces");
      void mutate("library");
    } catch (err) {
      dialog.current?.close();
      onError(err instanceof ApiError ? `Not deleted: ${err.message}.` : "Not deleted: the server couldn't be reached.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {variant === "icon" ? (
        <button
          type="button"
          onClick={() => dialog.current?.show()}
          aria-label={`Delete ${ws.title}`}
          className={`grid size-9 place-items-center rounded-full transition-colors hover:bg-white/10 hover:text-[#ff9b9b] ${focusRing}`}
          style={{ color: C.muted }}
        >
          <Trash className="size-4" aria-hidden />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => dialog.current?.show()}
          aria-label={`Delete ${ws.title}`}
          className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-colors hover:bg-[rgba(255,155,155,.08)] sm:min-h-9 ${focusRing}`}
          style={{ border: "1px solid rgba(255,155,155,.35)", color: C.danger }}
        >
          <Trash className="size-3.5" aria-hidden />
          Delete
        </button>
      )}
      <CinematicDialog ref={dialog} title={`Delete ${ws.title}?`}>
        <p className="text-[14px] leading-relaxed" style={{ color: C.muted }}>
          Its {papers} paper{papers === 1 ? "" : "s"} stay in your library. Its research trail and your review of it, its chats, comparisons, gaps and
          directions are deleted. This can&apos;t be undone.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            className={`rounded-full px-4 py-2 text-sm font-semibold hover:bg-white/10 ${focusRing}`}
            style={{ ...quietButton, color: C.ink }}
          >
            Keep it
          </button>
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className={`rounded-full px-4 py-2 text-sm font-semibold transition-opacity disabled:opacity-60 ${focusRing}`}
            style={{ background: "#ff9b9b", color: "#2a0606" }}
          >
            {busy ? "Deleting…" : "Delete workspace"}
          </button>
        </div>
      </CinematicDialog>
    </>
  );
}
