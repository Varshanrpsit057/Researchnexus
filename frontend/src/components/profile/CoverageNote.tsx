"use client";

import { useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { ArrowClockwise, FileText, UploadSimple, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { papers } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { Paper } from "@/lib/api/types";
import { CINEMATIC as C } from "@/lib/cinematic-theme";
import { COVERAGE_LABEL, coverageAction, coverageDetail, sourceLabel } from "@/lib/coverage";

/**
 * What text a paper is read from, and -- when it only has its abstract --
 * the ways to get more (remediation Phase 7): look for an open-access copy
 * (up to a minute: the sources are asked in turn and a PDF is downloaded and
 * read), or upload the PDF the reader has (2026-10-02 -- a paywalled
 * publisher's copy can't be fetched, but the reader's own can be read).
 * An uploaded paper can be read again with the current reader.
 */
export function CoverageNote({ paper }: { paper: Paper }) {
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const coverage = paper.coverage;
  if (!coverage) return null;
  const action = coverageAction(coverage);
  const tone = coverage.state === "full_text" ? C.mint : coverage.state === "retrieval_failed" ? C.warning : C.muted;

  async function retrieve() {
    setBusy(true);
    setNote(null);
    try {
      const res = await papers.retrieveFullText(paper.id);
      const { status, source, chunks } = res.outcome;
      setNote(
        status === "retrieved"
          ? { ok: true, text: `Full text retrieved from ${sourceLabel(source)}: ${chunks} passages to read.` }
          : { ok: false, text: status === "failed" ? "The full text couldn't be used this time." : "No full text could be found." },
      );
      await Promise.all([mutate(["paper", paper.id]), mutate(["profile", paper.id])]);
    } catch (err) {
      setNote({ ok: false, text: err instanceof ApiError ? err.message : "The server couldn't be reached. Try again." });
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    await Promise.all([mutate(["paper", paper.id]), mutate(["profile", paper.id])]);
  }

  async function upload(file: File) {
    setBusy(true);
    setNote(null);
    try {
      const res = await papers.uploadPdf(paper.id, file);
      setNote({
        ok: true,
        text: `Read from your PDF: ${res.outcome.chunks} passages${res.outcome.abstract_found ? ", with its abstract" : ""}. Analyse it again to update its profile.`,
      });
      await refresh();
    } catch (err) {
      setNote({ ok: false, text: err instanceof ApiError ? `That PDF couldn't be used: ${err.message}.` : "The server couldn't be reached. Try again." });
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function reread() {
    setBusy(true);
    setNote(null);
    try {
      const res = await papers.reread(paper.id);
      const filled = res.metadata.filled ?? [];
      setNote({
        ok: true,
        text:
          `Read again: ${res.outcome.chunks} passages${res.outcome.abstract_found ? ", abstract found" : ", no abstract in the PDF"}.` +
          (filled.length > 0 ? ` Its record gained: ${filled.join(", ")}.` : ""),
      });
      await refresh();
    } catch (err) {
      setNote({ ok: false, text: err instanceof ApiError ? err.message : "The server couldn't be reached. Try again." });
    } finally {
      setBusy(false);
    }
  }

  const quiet = "inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-full px-4 text-[13px] font-semibold transition-colors hover:bg-white/10 disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5df0a8]";
  const quietStyle = { background: "rgba(255,255,255,.05)", border: `1px solid ${C.lineStrong}`, color: C.ink };
  const canUpload = coverage.state !== "full_text";
  const canReread = coverage.state === "full_text" && paper.source === "upload";

  return (
    <div className="flex flex-wrap items-start gap-x-4 gap-y-2 rounded-xl px-4 py-3" style={{ background: "rgba(0,0,0,.22)" }} data-testid="coverage">
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 text-[13.5px] font-semibold" style={{ color: tone }}>
          {coverage.state === "retrieval_failed" ? (
            <WarningCircle className="size-4 shrink-0" weight="bold" aria-hidden />
          ) : (
            <FileText className="size-4 shrink-0" weight={coverage.state === "full_text" ? "fill" : "regular"} aria-hidden />
          )}
          {COVERAGE_LABEL[coverage.state]}
        </p>
        <p className="mt-0.5 text-[13px] leading-relaxed" style={{ color: C.muted }}>
          {coverageDetail(coverage)}
        </p>
        {note && (
          <p role="status" className="mt-1 text-[13px]" style={{ color: note.ok ? C.mint : C.warning }}>
            {note.text}
          </p>
        )}
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        {action && (
          <button type="button" onClick={retrieve} disabled={busy} className={quiet} style={quietStyle}>
            {busy ? "Working…" : action}
          </button>
        )}
        {canUpload && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              tabIndex={-1}
              aria-hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void upload(file);
              }}
              data-testid="paper-pdf-input"
            />
            <button type="button" onClick={() => fileRef.current?.click()} disabled={busy} className={quiet} style={quietStyle}>
              <UploadSimple className="size-4" aria-hidden />
              Upload the PDF
            </button>
          </>
        )}
        {canReread && (
          <button type="button" onClick={reread} disabled={busy} className={quiet} style={quietStyle}>
            <ArrowClockwise className="size-4" aria-hidden />
            {busy ? "Reading…" : "Read the PDF again"}
          </button>
        )}
      </div>
    </div>
  );
}
