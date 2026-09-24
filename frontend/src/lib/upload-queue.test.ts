import { describe, expect, it, vi } from "vitest";
import type { IngestResult } from "@/lib/paper-upload";
import { createUploadQueue, type UploadQueueDeps } from "./upload-queue";

function pdf(name: string): File {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

/** An ingest whose calls stay pending until the test settles them. */
function controlledIngest() {
  const calls: { file: File; resolve: (r: IngestResult) => void; reject: (e: unknown) => void; parsing: () => void }[] = [];
  const ingest: UploadQueueDeps["ingest"] = (file, onParsing) =>
    new Promise<IngestResult>((resolve, reject) => {
      calls.push({ file, resolve, reject, parsing: onParsing });
    });
  return { ingest, calls };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("createUploadQueue", () => {
  it("runs at most `concurrency` uploads at once and starts the next as one finishes", async () => {
    const { ingest, calls } = controlledIngest();
    const q = createUploadQueue({ ingest, addToWorkspace: async (ids) => ids, concurrency: 2 });
    q.add([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")]);

    expect(calls.map((c) => c.file.name)).toEqual(["a.pdf", "b.pdf"]);
    expect(q.getSnapshot().map((i) => i.status)).toEqual(["uploading", "uploading", "queued"]);

    calls[0].parsing();
    expect(q.getSnapshot()[0].status).toBe("parsing");
    calls[0].resolve({ paperId: "pap_a", deduplicated: false });
    await flush();
    expect(calls.map((c) => c.file.name)).toEqual(["a.pdf", "b.pdf", "c.pdf"]);
  });

  it("adds each parsed paper to the workspace and reports new vs already-present papers", async () => {
    const { ingest, calls } = controlledIngest();
    const onAdded = vi.fn();
    const q = createUploadQueue({ ingest, addToWorkspace: async (ids) => ids.filter((id) => id !== "pap_seed"), onAdded });
    q.add([pdf("a.pdf"), pdf("seed.pdf")]);
    calls[0].resolve({ paperId: "pap_a", deduplicated: false });
    calls[1].resolve({ paperId: "pap_seed", deduplicated: true });
    await flush();
    await flush();
    expect(q.getSnapshot().map((i) => i.status)).toEqual(["added", "already"]);
    expect(onAdded).toHaveBeenCalled();
  });

  it("sends papers that finish during an in-flight add together in the next request", async () => {
    const { ingest, calls } = controlledIngest();
    let releaseFirst: () => void = () => {};
    const batches: string[][] = [];
    const addToWorkspace = vi.fn(async (ids: string[]) => {
      batches.push(ids);
      if (batches.length === 1) await new Promise<void>((r) => (releaseFirst = r));
      return ids;
    });
    const q = createUploadQueue({ ingest, addToWorkspace, concurrency: 3 });
    q.add([pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")]);

    calls[0].resolve({ paperId: "pap_a", deduplicated: false });
    await flush();
    calls[1].resolve({ paperId: "pap_b", deduplicated: false });
    calls[2].resolve({ paperId: "pap_c", deduplicated: false });
    await flush();
    releaseFirst();
    await flush();
    await flush();

    expect(batches).toEqual([["pap_a"], ["pap_b", "pap_c"]]);
    expect(q.getSnapshot().every((i) => i.status === "added")).toBe(true);
  });

  it("marks a failed upload without stopping the others, and retries it on request", async () => {
    const { ingest, calls } = controlledIngest();
    const q = createUploadQueue({ ingest, addToWorkspace: async (ids) => ids });
    q.add([pdf("bad.pdf"), pdf("good.pdf")]);
    calls[0].reject(new Error("This PDF is password-protected."));
    calls[1].resolve({ paperId: "pap_good", deduplicated: false });
    await flush();
    await flush();
    expect(q.getSnapshot().map((i) => [i.status, i.message])).toEqual([
      ["failed", "This PDF is password-protected."],
      ["added", undefined],
    ]);

    q.retry(q.getSnapshot()[0].key);
    expect(calls).toHaveLength(3);
    expect(q.getSnapshot()[0].status).toBe("uploading");
  });

  it("retries a failed add without uploading the file again", async () => {
    const { ingest, calls } = controlledIngest();
    let fail = true;
    const addToWorkspace = vi.fn(async (ids: string[]) => {
      if (fail) throw new TypeError("Failed to fetch");
      return ids;
    });
    const q = createUploadQueue({ ingest, addToWorkspace });
    q.add([pdf("a.pdf")]);
    calls[0].resolve({ paperId: "pap_a", deduplicated: false });
    await flush();
    await flush();
    expect(q.getSnapshot()[0]).toMatchObject({ status: "failed", paperId: "pap_a" });
    expect(q.getSnapshot()[0].message).toMatch(/Uploaded, but not added/);

    fail = false;
    q.retry(q.getSnapshot()[0].key);
    await flush();
    await flush();
    expect(q.getSnapshot()[0].status).toBe("added");
    expect(calls).toHaveLength(1);
  });

  it("refuses a non-PDF up front without sending it", () => {
    const { ingest, calls } = controlledIngest();
    const q = createUploadQueue({ ingest, addToWorkspace: async (ids) => ids });
    q.add([new File(["x"], "notes.docx", { type: "application/msword" })]);
    expect(calls).toHaveLength(0);
    expect(q.getSnapshot()[0]).toMatchObject({ status: "failed", message: "Not a PDF file." });
  });

  it("clears finished rows but never one still in progress", async () => {
    const { ingest, calls } = controlledIngest();
    const q = createUploadQueue({ ingest, addToWorkspace: async (ids) => ids });
    q.add([pdf("a.pdf"), pdf("b.pdf")]);
    calls[0].resolve({ paperId: "pap_a", deduplicated: false });
    await flush();
    await flush();
    q.clearFinished();
    expect(q.getSnapshot().map((i) => i.file.name)).toEqual(["b.pdf"]);
  });
});
