import { ApiError } from "@/lib/api/client";
import { checkPdfFile, type IngestResult } from "@/lib/paper-upload";

export type UploadStatus = "queued" | "uploading" | "parsing" | "adding" | "added" | "already" | "failed";

export interface UploadItem {
  key: string;
  file: File;
  status: UploadStatus;
  message?: string;
  /** Set once the server has the paper -- a failed add retries without re-uploading. */
  paperId?: string;
}

export const BUSY_STATUSES: readonly UploadStatus[] = ["queued", "uploading", "parsing", "adding"];

export interface UploadQueueDeps {
  /** Upload one file and wait for the server to parse it. */
  ingest: (file: File, onParsing: () => void) => Promise<IngestResult>;
  /** Add papers to the workspace; resolves with the ids that were newly added. */
  addToWorkspace: (paperIds: string[]) => Promise<string[]>;
  onUploaded?: (paperId: string, file: File) => void;
  onAdded?: () => Promise<void> | void;
  concurrency?: number;
}

export function addErrorMessage(err: unknown): string {
  return err instanceof ApiError ? `${err.message}. Try again.` : "The server couldn't be reached. Try again.";
}

/** A queue of PDFs being uploaded into one workspace, kept outside React so
 * it survives the panel being closed and can be tested on its own.
 *
 * Uploads run `concurrency` at a time (each is a server-side parse). Parsed
 * papers are added in batches: ids that finish while an add request is in
 * flight go out together in the next one, so the workspace index is rebuilt
 * once per batch rather than once per file. */
export function createUploadQueue(deps: UploadQueueDeps) {
  const concurrency = deps.concurrency ?? 2;
  let items: UploadItem[] = [];
  let seq = 0;
  let active = 0;
  let adding = false;
  let onAdded = deps.onAdded;
  const pendingAdd = new Set<string>();
  const listeners = new Set<() => void>();

  function set(next: UploadItem[]) {
    items = next;
    for (const listener of listeners) listener();
  }

  function patch(key: string, changes: Partial<UploadItem>) {
    set(items.map((it) => (it.key === key ? { ...it, ...changes } : it)));
  }

  function pump() {
    for (const it of items) {
      if (active >= concurrency) return;
      if (it.status === "queued") start(it);
    }
  }

  function start(it: UploadItem) {
    active++;
    patch(it.key, { status: "uploading", message: undefined });
    deps
      .ingest(it.file, () => patch(it.key, { status: "parsing" }))
      .then(
        ({ paperId }) => {
          deps.onUploaded?.(paperId, it.file);
          queueAdd(it.key, paperId);
        },
        (err: unknown) => patch(it.key, { status: "failed", message: err instanceof Error ? err.message : "Upload failed. Try again." }),
      )
      .finally(() => {
        active--;
        pump();
      });
  }

  function queueAdd(key: string, paperId: string) {
    patch(key, { status: "adding", paperId, message: undefined });
    pendingAdd.add(paperId);
    void flushAdds();
  }

  async function flushAdds(): Promise<void> {
    if (adding || pendingAdd.size === 0) return;
    adding = true;
    const batch = [...pendingAdd];
    pendingAdd.clear();
    const inBatch = (it: UploadItem) => it.status === "adding" && it.paperId !== undefined && batch.includes(it.paperId);
    try {
      const added = new Set(await deps.addToWorkspace(batch));
      set(items.map((it) => (inBatch(it) ? { ...it, status: added.has(it.paperId!) ? "added" : "already" } : it)));
      await onAdded?.();
    } catch (err) {
      const message = `Uploaded, but not added to the workspace: ${addErrorMessage(err)}`;
      set(items.map((it) => (inBatch(it) ? { ...it, status: "failed", message } : it)));
    } finally {
      adding = false;
      void flushAdds();
    }
  }

  return {
    getSnapshot: () => items,
    /** Swap the after-add callback (it may be recreated on every render). */
    setOnAdded(fn: UploadQueueDeps["onAdded"]) {
      onAdded = fn;
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    add(files: Iterable<File>) {
      const incoming = Array.from(files, (file): UploadItem => {
        const problem = checkPdfFile(file);
        return { key: `u${seq++}`, file, status: problem ? "failed" : "queued", message: problem ?? undefined };
      });
      if (incoming.length === 0) return;
      set([...items, ...incoming]);
      pump();
    },
    retry(key: string) {
      const it = items.find((x) => x.key === key);
      if (!it || it.status !== "failed") return;
      if (it.paperId) {
        queueAdd(key, it.paperId); // already on the server; only the add failed
        return;
      }
      if (checkPdfFile(it.file)) return; // nothing a retry can fix
      patch(key, { status: "queued", message: undefined });
      pump();
    },
    dismiss(key: string) {
      set(items.filter((it) => it.key !== key || BUSY_STATUSES.includes(it.status)));
    },
    clearFinished() {
      set(items.filter((it) => BUSY_STATUSES.includes(it.status)));
    },
  };
}

export type UploadQueue = ReturnType<typeof createUploadQueue>;
