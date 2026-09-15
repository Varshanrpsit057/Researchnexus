import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ApiError } from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("apiFetch error handling", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("extracts code and message from the real FastAPI {detail: {error}} envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(409, { detail: { error: { code: "llm_key_required", message: "no working LLM provider key saved" } } })
      )
    );

    await expect(apiFetch("/api/v1/papers/pap_1/analyze")).rejects.toMatchObject({
      status: 409,
      code: "llm_key_required",
      message: "no working LLM provider key saved",
    });
  });

  it("does not mistake a bare {error} body (no detail wrapper) for the real shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(500, { error: { code: "server_error", message: "boom" } }))
    );

    let err: unknown;
    try {
      await apiFetch("/api/v1/papers/pap_1");
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(ApiError);
    // No `detail` wrapper -> falls back to the generic message, not the
    // misread "server_error" -- this is the exact bug that made every error
    // in the app show a generic status-text message instead of the real one.
    expect((err as ApiError).code).toBe("unknown_error");
  });

  it("falls back to a generic message when the body isn't JSON at all", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 502, statusText: "Bad Gateway" })));

    await expect(apiFetch("/api/v1/papers/pap_1")).rejects.toMatchObject({
      status: 502,
      code: "unknown_error",
      message: "Bad Gateway",
    });
  });

  it("returns parsed JSON on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { id: "pap_1", title: "Seed" })));
    await expect(apiFetch("/api/v1/papers/pap_1")).resolves.toEqual({ id: "pap_1", title: "Seed" });
  });

  it("treats 204 as no content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(apiFetch("/api/v1/settings/llm-keys/openai")).resolves.toBeUndefined();
  });
});
