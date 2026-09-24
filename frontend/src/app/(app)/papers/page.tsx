"use client";

import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { useRouter } from "next/navigation";
import { FileArrowUp, FilePdf, MagnifyingGlass } from "@phosphor-icons/react/dist/ssr";
import { papers } from "@/lib/api/endpoints";
import { useJobPolling } from "@/lib/api/hooks";
import { recordRecentPaper, useRecentPapers } from "@/lib/local-history";
import { uploadErrorMessage } from "@/lib/paper-upload";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/States";
import { Card } from "@/components/ui/Card";

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading" }
  | { phase: "parsing"; paperId: string; jobId: string }
  | { phase: "error"; message: string };

export default function PapersPage() {
  const router = useRouter();
  const recent = useRecentPapers();
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const [dragActive, setDragActive] = useState(false);
  const [jumpId, setJumpId] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const polling = useJobPolling(state.phase === "parsing" ? state.jobId : null);

  useEffect(() => {
    if (state.phase === "parsing" && polling.isDone && polling.job?.status === "succeeded") {
      router.replace(`/papers/${state.paperId}`);
    }
  }, [state, polling.isDone, polling.job, router]);

  const handleFile = useCallback(async (file: File) => {
    if (file.type !== "application/pdf") {
      setState({ phase: "error", message: "Only PDF files are supported." });
      return;
    }
    setState({ phase: "uploading" });
    try {
      const res = await papers.upload(file);
      recordRecentPaper({ paperId: res.paper_id, title: file.name.replace(/\.pdf$/i, ""), addedAt: new Date().toISOString() });
      if (res.deduplicated || !res.job) {
        router.replace(`/papers/${res.paper_id}`);
        return;
      }
      setState({ phase: "parsing", paperId: res.paper_id, jobId: res.job.job_id });
    } catch (err) {
      setState({ phase: "error", message: uploadErrorMessage(err) });
    }
  }, [router]);

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  }

  const busy = state.phase === "uploading" || state.phase === "parsing";

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6 border-b border-border-strong pb-4">
        <h1 className="text-xl font-semibold tracking-tightest text-ink">Start from a seed paper</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Upload a PDF to extract its research profile, then discover and classify the related work around it.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        data-active={dragActive || undefined}
        className="flex flex-col items-center gap-3 border-2 border-dashed border-border-strong bg-surface-raised px-6 py-14 text-center transition-colors duration-150 data-[active]:border-accent data-[active]:bg-accent-wash"
      >
        <FileArrowUp className="size-8 text-ink-subtle" aria-hidden />
        <div>
          <p className="text-sm font-medium text-ink">Drag a PDF here, or</p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => inputRef.current?.click()} loading={busy}>
          {state.phase === "uploading" ? "Uploading…" : state.phase === "parsing" ? "Parsing…" : "Browse for a file"}
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFile(file);
            e.target.value = "";
          }}
        />
        <p className="text-xs text-ink-subtle">PDF only, up to 30 MB, 60 pages.</p>
      </div>

      {state.phase === "parsing" && (
        <p className="mt-3 text-center text-sm text-ink-muted" role="status" aria-live="polite">
          Validating, extracting structure, and building the seed index
          {polling.job?.status === "failed" ? " — this failed. Try re-uploading." : "…"}
        </p>
      )}
      {state.phase === "error" && (
        <div className="mt-3">
          <InlineError message={state.message} />
        </div>
      )}

      <form
        className="mt-8 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (jumpId.trim()) router.push(`/papers/${jumpId.trim()}`);
        }}
      >
        <div className="flex-1">
          <label htmlFor="jump-id" className="mb-1.5 block text-sm font-medium text-ink">
            Already have a paper ID?
          </label>
          <input
            id="jump-id"
            value={jumpId}
            onChange={(e) => setJumpId(e.target.value)}
            placeholder="pap_..."
            className="h-10 w-full rounded-sm border border-border-strong bg-surface-raised px-3 font-mono text-sm text-ink placeholder:text-ink-subtle focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
          />
        </div>
        <Button type="submit" variant="secondary" size="md">
          <MagnifyingGlass className="size-4" aria-hidden />
          Open
        </Button>
      </form>

      <div className="mt-10">
        <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-subtle">
          Recently uploaded in this browser
        </h2>
        {recent.length > 0 ? (
          <Card>
            <ul className="divide-y divide-border">
              {recent.map((p) => (
                <li key={p.paperId}>
                  <button
                    type="button"
                    onClick={() => router.push(`/papers/${p.paperId}`)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-sunken focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
                  >
                    <FilePdf className="size-4 shrink-0 text-ink-subtle" aria-hidden />
                    <span className="min-w-0 flex-1 truncate text-sm text-ink">{p.title}</span>
                    <span className="shrink-0 font-mono text-xs text-ink-subtle">{p.paperId}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        ) : (
          <p className="border border-border bg-surface-sunken/50 px-4 py-8 text-center text-sm text-ink-subtle">
            Papers you upload will appear here for quick access.
          </p>
        )}
      </div>
    </div>
  );
}
