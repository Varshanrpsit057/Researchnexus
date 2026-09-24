import { ApiError } from "@/lib/api/client";
import type { Job, UploadResponse } from "@/lib/api/types";

// Mirrors the backend's upload validation (config.py max_pdf_mb / max_pages),
// so an oversized file is refused before it is sent.
export const MAX_PDF_MB = 30;
export const MAX_PDF_PAGES = 60;

/** Paper ids pasted as one string: separated by commas, semicolons, spaces
 * or new lines. Order is kept and repeats are dropped. */
export function parsePaperIds(text: string): string[] {
  const ids: string[] = [];
  for (const part of text.split(/[\s,;]+/)) {
    const id = part.trim();
    if (id && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

/** A client-side check before uploading; null when the file can be sent. */
export function checkPdfFile(file: { name: string; type: string; size: number }): string | null {
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  if (!isPdf) return "Not a PDF file.";
  if (file.size > MAX_PDF_MB * 1024 * 1024) return `Larger than the ${MAX_PDF_MB} MB limit.`;
  return null;
}

/** The user-facing reason an upload was refused. */
export function uploadErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return "Upload failed: the server couldn't be reached. Try again.";
  if (err.status === 413 || err.code === "file_too_large") return `This file is larger than the ${MAX_PDF_MB} MB limit.`;
  if (err.status === 415 || err.code === "unsupported_media_type") return "This file is not a PDF.";
  switch (err.code) {
    case "pdf_scanned":
      return "This PDF has no extractable text layer (a scanned image). Try an OCR'd version.";
    case "pdf_encrypted":
      return "This PDF is password-protected.";
    case "too_many_pages":
      return `This PDF is longer than the ${MAX_PDF_PAGES}-page limit.`;
    case "pdf_invalid":
      return "This PDF is damaged or incomplete.";
    default:
      return err.message;
  }
}

export interface IngestDeps {
  upload: (file: File) => Promise<UploadResponse>;
  getJob: (jobId: string) => Promise<Job>;
  /** Called once the file is uploaded and the server has started parsing it. */
  onParsing?: () => void;
  sleep?: (ms: number) => Promise<void>;
  pollMs?: number;
  timeoutMs?: number;
}

export interface IngestResult {
  paperId: string;
  /** The same PDF was uploaded before; the existing paper is reused. */
  deduplicated: boolean;
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Upload one PDF and wait for the server to finish parsing it -- a paper
 * can only be added to a workspace once its ingest job has succeeded.
 * Throws an Error whose message is written for the user. */
export async function ingestPdf(file: File, deps: IngestDeps): Promise<IngestResult> {
  let res: UploadResponse;
  try {
    res = await deps.upload(file);
  } catch (err) {
    throw new Error(uploadErrorMessage(err));
  }
  if (res.deduplicated || !res.job) return { paperId: res.paper_id, deduplicated: true };

  deps.onParsing?.();
  const sleep = deps.sleep ?? wait;
  const deadline = Date.now() + (deps.timeoutMs ?? 180_000);
  for (;;) {
    let job: Job | null = null;
    try {
      job = await deps.getJob(res.job.job_id);
    } catch {
      // a dropped poll is not a failed parse; keep polling until the deadline
    }
    if (job?.status === "succeeded" || job?.status === "partial") return { paperId: res.paper_id, deduplicated: false };
    // job.error is a raw server exception string, not something to show a reader
    if (job?.status === "failed") throw new Error("The server couldn't read this PDF.");
    if (Date.now() >= deadline) throw new Error("Still processing after 3 minutes. Try again in a moment.");
    await sleep(deps.pollMs ?? 1500);
  }
}
