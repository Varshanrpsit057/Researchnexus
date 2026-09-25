import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChat } from "./chat-stream";
import { ApiError } from "./client";

function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i++]));
      } else {
        controller.close();
      }
    },
  });
}

function streamResponse(chunks: string[]): Response {
  return new Response(sseStream(chunks), { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("streamChat", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("dispatches token, citation, and done events as they arrive", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamResponse([
          `event: token\ndata: {"text":"RAG "}\n\n`,
          `event: token\ndata: {"text":"combines retrieval "}\n\n`,
          `event: citation\ndata: {"marker":"[1]","claim_id":"c1","paper_id":"pap_1","chunk_id":"chk_1","quote":"we propose RAG","section":"Abstract","page":1}\n\n`,
          `event: done\ndata: {"message_id":"msg_1","session_id":"sess_1","answerable":true,"faithfulness":0.9}\n\n`,
        ])
      )
    );

    const onToken = vi.fn();
    const onCitation = vi.fn();
    const onDone = vi.fn();

    await streamChat("ws_1", { message: "how does it work?" }, { onToken, onCitation, onDone });

    expect(onToken).toHaveBeenNthCalledWith(1, "RAG ");
    expect(onToken).toHaveBeenNthCalledWith(2, "combines retrieval ");
    expect(onCitation).toHaveBeenCalledWith(expect.objectContaining({ marker: "[1]", paper_id: "pap_1" }));
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ session_id: "sess_1", faithfulness: 0.9 }));
  });

  it("reports each pipeline stage, and a mid-stream failure with its code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamResponse([
          `event: status
data: {"stage":"searching"}

`,
          `event: status
data: {"stage":"reading"}

`,
          `event: error
data: {"code":"generation_failed","message":"No usable answer."}

`,
        ])
      )
    );
    const onStatus = vi.fn();
    const onError = vi.fn();
    await streamChat("ws_1", { message: "q", regenerate: true, session_id: "cs_1" }, { onStatus, onError });
    expect(onStatus.mock.calls.map(([s]) => s.stage)).toEqual(["searching", "reading"]);
    expect(onError).toHaveBeenCalledWith("No usable answer.", "generation_failed");
    const body = JSON.parse((vi.mocked(fetch).mock.calls[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({ regenerate: true, session_id: "cs_1" });
  });

  it("splits events that arrive split across multiple stream chunks", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(streamResponse([`event: token\ndata: {"te`, `xt":"hi"}\n\n`]))
    );
    const onToken = vi.fn();
    await streamChat("ws_1", { message: "hi" }, { onToken });
    expect(onToken).toHaveBeenCalledWith("hi");
  });

  it("rejects with an ApiError built from the real {detail: {error}} envelope on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: { error: { code: "llm_key_required", message: "no working LLM provider key saved" } } }), {
          status: 409,
        })
      )
    );

    await expect(streamChat("ws_1", { message: "hi" }, {})).rejects.toMatchObject({
      status: 409,
      code: "llm_key_required",
      message: "no working LLM provider key saved",
    });
  });

  it("still throws an ApiError when the error response has no detail wrapper", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ oops: true }), { status: 500 })));
    let err: unknown;
    try {
      await streamChat("ws_1", { message: "hi" }, {});
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
  });
});
