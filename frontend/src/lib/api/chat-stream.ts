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
  onError?: (message: string, code?: string) => void;
}

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

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      dispatchEvent(rawEvent, callbacks);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function dispatchEvent(raw: string, callbacks: ChatStreamCallbacks): void {
  let eventName = "message";
  let dataLine = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
  }
  if (!dataLine) return;

  let data: unknown;
  try {
    data = JSON.parse(dataLine);
  } catch {
    return;
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
      callbacks.onError?.(err.message, err.code);
      break;
    }
  }
}
