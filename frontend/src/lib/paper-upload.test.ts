import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { Job, JobStatus, UploadResponse } from "@/lib/api/types";
import { checkPdfFile, ingestPdf, parsePaperIds, uploadErrorMessage } from "./paper-upload";

const file = new File(["%PDF-1.4"], "paper.pdf", { type: "application/pdf" });

function uploaded(overrides: Partial<UploadResponse> = {}): UploadResponse {
  return {
    paper_id: "pap_1",
    file: { sha256: "x", size_bytes: 8, page_count: 1 },
    job: { job_id: "job_1", kind: "ingest", status: "queued", poll_url: "/api/v1/jobs/job_1" },
    ...overrides,
  } as UploadResponse;
}

function job(status: JobStatus): Job {
  return {
    job_id: "job_1",
    owner_id: "usr_dev",
    workspace_id: null,
    kind: "ingest",
    status,
    progress: {},
    result_ref: null,
    error: status === "failed" ? "IndexError: list index out of range" : null,
    created_at: "",
    updated_at: "",
  } as Job;
}

const noSleep = () => Promise.resolve();

describe("parsePaperIds", () => {
  it("splits on commas, spaces and new lines, dropping blanks and repeats", () => {
    expect(parsePaperIds(" pap_a, pap_b\npap_c;pap_a  ,, ")).toEqual(["pap_a", "pap_b", "pap_c"]);
  });

  it("returns nothing for blank input", () => {
    expect(parsePaperIds("  \n ")).toEqual([]);
  });
});

describe("checkPdfFile", () => {
  it("accepts a PDF under the size limit", () => {
    expect(checkPdfFile({ name: "a.pdf", type: "application/pdf", size: 1024 })).toBeNull();
  });

  it("accepts a .pdf name even when the browser reports no type", () => {
    expect(checkPdfFile({ name: "a.PDF", type: "", size: 1024 })).toBeNull();
  });

  it("refuses other files and oversized PDFs", () => {
    expect(checkPdfFile({ name: "a.docx", type: "application/msword", size: 10 })).toBe("Not a PDF file.");
    expect(checkPdfFile({ name: "a.pdf", type: "application/pdf", size: 31 * 1024 * 1024 })).toMatch(/30 MB/);
  });
});

describe("uploadErrorMessage", () => {
  it("explains each validation refusal in plain language", () => {
    expect(uploadErrorMessage(new ApiError(422, "pdf_scanned", "raw"))).toMatch(/scanned image/);
    expect(uploadErrorMessage(new ApiError(422, "too_many_pages", "raw"))).toMatch(/60-page/);
    expect(uploadErrorMessage(new ApiError(413, "file_too_large", "raw"))).toMatch(/30 MB/);
  });

  it("does not blame the file when the server is unreachable", () => {
    expect(uploadErrorMessage(new TypeError("Failed to fetch"))).toMatch(/couldn't be reached/);
  });
});

describe("ingestPdf", () => {
  it("waits for the parse job to succeed, then returns the paper id", async () => {
    const statuses: JobStatus[] = ["queued", "running", "succeeded"];
    const getJob = vi.fn(async () => job(statuses.shift()!));
    const onParsing = vi.fn();
    const result = await ingestPdf(file, { upload: async () => uploaded(), getJob, onParsing, sleep: noSleep });
    expect(result).toEqual({ paperId: "pap_1", deduplicated: false });
    expect(getJob).toHaveBeenCalledTimes(3);
    expect(onParsing).toHaveBeenCalledOnce();
  });

  it("reuses an already-uploaded paper without polling", async () => {
    const getJob = vi.fn();
    const result = await ingestPdf(file, {
      upload: async () => uploaded({ job: null, deduplicated: true }),
      getJob,
      sleep: noSleep,
    });
    expect(result).toEqual({ paperId: "pap_1", deduplicated: true });
    expect(getJob).not.toHaveBeenCalled();
  });

  it("keeps polling through a dropped request", async () => {
    let calls = 0;
    const getJob = async () => {
      calls += 1;
      if (calls === 1) throw new TypeError("Failed to fetch");
      return job("succeeded");
    };
    await expect(ingestPdf(file, { upload: async () => uploaded(), getJob, sleep: noSleep })).resolves.toMatchObject({
      paperId: "pap_1",
    });
  });

  it("reports a failed parse without leaking the server exception", async () => {
    const promise = ingestPdf(file, { upload: async () => uploaded(), getJob: async () => job("failed"), sleep: noSleep });
    await expect(promise).rejects.toThrow("The server couldn't read this PDF.");
  });

  it("turns an upload refusal into its plain-language reason", async () => {
    const upload = async () => {
      throw new ApiError(422, "pdf_encrypted", "raw");
    };
    await expect(ingestPdf(file, { upload, getJob: vi.fn(), sleep: noSleep })).rejects.toThrow(/password-protected/);
  });

  it("gives up once the deadline passes", async () => {
    const promise = ingestPdf(file, {
      upload: async () => uploaded(),
      getJob: async () => job("running"),
      sleep: noSleep,
      timeoutMs: 0,
    });
    await expect(promise).rejects.toThrow(/Still processing/);
  });
});
