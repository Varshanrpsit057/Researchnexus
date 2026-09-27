import { getToken } from "@/lib/auth/token";
import { API_BASE_URL, ApiError } from "./client";
import type { SseCitationEvent, SseDoneEvent, SseErrorEvent, SseStatusEvent, SseUsageEvent } from "./types";

interface ChatStreamCallbacks {
  /** The pipeline reached a stage (searching, reading, writing, checking, rewriting). */
  onStatus?: (status: SseStatusEvent) => void;
  onToken?: (text: string) => void;
  onCitation?: (citation: SseCitationEvent) => void;
  onUsage?: (usage: SseUsageEvent) => void;
  onDone?: (done: SseDoneEvent) => void;
  /** `kind` says which provider failure it was (auth, insufficient_balance, ...). */
  onError?: (message: string, code?: string, kind?: string) => void;
}

/** The stream closed before the answer was done or a failure was reported. */
export const INTERRUPTED = "The answer stopped before it finished. Try again.";

interface ChatStreamBody {
  message: string;
  session_id?: string | null;
  scope?: "all" | { paper_ids: string[] };
  /** Re-answer the session's last question, replacing its answer. */
  regenerate?: boolean;
}

/**
 * The backend's chat SSE stream is plain fetch + ReadableStream, not
 * EventSource -- EventSource cannot send a POST body or a custom
 * Authorization header, both of which this endpoint requires.
 *
 * Events are separated by a blank line (LF or CRLF); `: keep-alive`
 * comments are skipped. A stream that ends without `done` or `error` --
 * the connection dropped, the server stopped -- is reported through
 * `onError` with the code `stream_interrupted`, so a caller is never left
 * waiting for an answer that will not come.
 */
export async function streamChat(
  workspaceId: string,
  body: ChatStreamBody,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE_URL}/api/v1/workspaces/${workspaceId}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    let message = `Chat request failed (${res.status})`;
    try {
      // FastAPI wraps HTTPException(detail=...) as {"detail": {"error": {...}}},
      // not {"error": {...}} -- see client.ts's parseErrorBody for the same fix.
      const errBody = await res.json();
      const error = errBody?.detail?.error;
      message = error?.message ?? message;
      throw new ApiError(res.status, error?.code ?? "unknown_error", message);
    } catch (e) {
      if (e instanceof ApiError) throw e;
      throw new ApiError(res.status, "unknown_error", message);
    }
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  const dispatch = (raw: string) => {
    const name = dispatchEvent(raw, callbacks);
    if (name === "done" || name === "error") finished = true;
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // a CRLF pair split across two reads is joined before it is normalised
    const normalised = buffer.endsWith("\r") ? buffer.slice(0, -1) : buffer;
    const held = buffer.endsWith("\r") ? "\r" : "";
    buffer = normalised.replace(/\r\n?/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      dispatch(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
    buffer += held;
  }
  if (buffer.trim()) dispatch(buffer.replace(/\r\n?/g, "\n"));
  if (!finished) callbacks.onError?.(INTERRUPTED, "stream_interrupted");
}

/** Hands one event to its callback; returns the event's name, or null for a comment. */
function dispatchEvent(raw: string, callbacks: ChatStreamCallbacks): string | null {
  let eventName = "message";
  let dataLine = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith(":")) continue; // a keep-alive comment
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
  }
  if (!dataLine) return null;

  let data: unknown;
  try {
    data = JSON.parse(dataLine);
  } catch {
    return null;
  }

  switch (eventName) {
    case "status":
      callbacks.onStatus?.(data as SseStatusEvent);
      break;
    case "token":
      callbacks.onToken?.((data as { text: string }).text);
      break;
    case "citation":
      callbacks.onCitation?.(data as SseCitationEvent);
      break;
    case "usage":
      callbacks.onUsage?.(data as SseUsageEvent);
      break;
    case "done":
      callbacks.onDone?.(data as SseDoneEvent);
      break;
    case "error": {
      const err = data as SseErrorEvent;
      callbacks.onError?.(err.message, err.code, err.kind);
      break;
    }
  }
  return eventName;
}
