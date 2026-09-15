"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { PaperPlaneTilt, Plus } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import { streamChat } from "@/lib/api/chat-stream";
import { ApiError } from "@/lib/api/client";
import type { ChatMessage, SseCitationEvent } from "@/lib/api/types";
import { Card, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { InlineError, Skeleton } from "@/components/ui/States";

export default function WorkspaceChatPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { data: sessionsData, mutate: refetchSessions } = useSWR(
    ["chat-sessions", workspaceId],
    () => workspaces.chatSessions(workspaceId)
  );

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);

  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [streamingCitations, setStreamingCitations] = useState<SseCitationEvent[]>([]);
  // Rich per-citation payloads (quote/section/page) only exist transiently
  // over SSE -- the persisted ChatMessage/Claim shape has no quote/span
  // field to reload them from, so this only ever covers messages sent in
  // the current browser session (a real, disclosed ceiling, not a bug).
  const [citationsByMessageId, setCitationsByMessageId] = useState<Record<string, SseCitationEvent[]>>({});
  const citationsRef = useRef<SseCitationEvent[]>([]);
  // `suggestion` (what to try instead of an unanswerable question) and
  // `unsupported_dropped` (how many claims were cut for lacking support)
  // exist only on the SSE `done` event -- the persisted ChatMessage has no
  // column for either, so a plain re-fetch after streaming silently drops
  // them, the same ceiling as citationsByMessageId above and for the same
  // reason: real transparency the product principles call for, kept only
  // for the messages sent in this browser session.
  const [metaByMessageId, setMetaByMessageId] = useState<Record<string, { suggestion?: string | null; unsupportedDropped?: number }>>({});
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function openSession(sessionId: string) {
    setActiveSessionId(sessionId);
    setLoadingThread(true);
    try {
      const detail = await workspaces.chatSession(workspaceId, sessionId);
      setMessages(detail.messages);
    } finally {
      setLoadingThread(false);
    }
  }

  function startNewChat() {
    setActiveSessionId(null);
    setMessages([]);
    setError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || streaming) return;

    setInput("");
    setError(null);
    setMessages((prev) => [
      ...prev,
      {
        message_id: `local_${Date.now()}`,
        session_id: activeSessionId ?? "",
        role: "user",
        content: message,
        citations: [],
        tokens_prompt: 0,
        tokens_completion: 0,
        faithfulness: null,
        answerable: true,
        created_at: new Date().toISOString(),
      },
    ]);
    setStreaming(true);
    setStreamingText("");
    setStreamingCitations([]);
    citationsRef.current = [];

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat(
        workspaceId,
        { message, session_id: activeSessionId },
        {
          onToken: (text) => setStreamingText((prev) => prev + text),
          onCitation: (c) => {
            citationsRef.current = [...citationsRef.current, c];
            setStreamingCitations((prev) => [...prev, c]);
          },
          onDone: async (done) => {
            setActiveSessionId(done.session_id);
            if (citationsRef.current.length > 0) {
              setCitationsByMessageId((prev) => ({ ...prev, [done.message_id]: citationsRef.current }));
            }
            if (done.suggestion || done.unsupported_dropped) {
              setMetaByMessageId((prev) => ({
                ...prev,
                [done.message_id]: { suggestion: done.suggestion, unsupportedDropped: done.unsupported_dropped },
              }));
            }
            const detail = await workspaces.chatSession(workspaceId, done.session_id);
            setMessages(detail.messages);
            setStreaming(false);
            setStreamingText("");
            setStreamingCitations([]);
            refetchSessions();
          },
          onError: (msg) => {
            setError(msg);
            setStreaming(false);
          },
        },
        controller.signal
      );
    } catch (err) {
      if (err instanceof ApiError && err.code === "llm_key_required") {
        setError("No working LLM provider key is saved yet. Add one in Settings, then try again.");
      } else {
        setError(err instanceof ApiError ? err.message : "Chat failed. Try again.");
      }
      setStreaming(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[200px_1fr]">
      <div className="space-y-3">
        <Button size="sm" variant="secondary" className="w-full" onClick={startNewChat}>
          <Plus className="size-4" aria-hidden />
          New chat
        </Button>
        <ul className="space-y-0.5 border-t border-border pt-2">
          {sessionsData?.sessions.map((s) => (
            <li key={s.session_id}>
              <button
                type="button"
                onClick={() => openSession(s.session_id)}
                aria-current={s.session_id === activeSessionId ? "true" : undefined}
                className={`w-full truncate rounded-sm px-2.5 py-1.5 text-left text-sm transition-colors ${
                  s.session_id === activeSessionId ? "bg-accent-wash text-accent-strong" : "text-ink-muted hover:bg-surface-sunken hover:text-ink"
                }`}
              >
                {s.title ?? "Untitled chat"}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex min-h-[28rem] flex-col">
        <div className="flex-1 space-y-3 overflow-y-auto">
          {loadingThread && <Skeleton className="h-16 w-full" />}
          {!loadingThread && messages.length === 0 && !streaming && (
            <p className="py-10 text-center text-sm text-ink-subtle">
              Ask a question answered from this workspace&apos;s papers. Every claim is grounded in a cited source.
            </p>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.message_id} message={m} citations={citationsByMessageId[m.message_id]} meta={metaByMessageId[m.message_id]} />
          ))}
          {streaming && (
            <div className="mr-8 border border-border bg-surface-raised px-4 py-3">
              <p className="max-w-[70ch] whitespace-pre-wrap text-sm text-ink">
                <CitedText text={streamingText || "…"} citations={streamingCitations} />
              </p>
            </div>
          )}
        </div>

        {error && (
          <div className="mt-2">
            <InlineError message={error} />
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-3 flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
            placeholder="Ask about this workspace's papers…"
            rows={2}
            disabled={streaming}
            className="min-h-16 flex-1 rounded-sm border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink placeholder:text-ink-subtle focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)] disabled:opacity-60"
          />
          <Button type="submit" loading={streaming} disabled={!input.trim()}>
            <PaperPlaneTilt className="size-4" aria-hidden />
            Send
          </Button>
        </form>
      </div>
    </div>
  );
}

/** Splits `text` on each citation's marker (e.g. "[1]") and renders the
 * marker as an inline, hover/focus-expandable source instead of a flat
 * list after the fact -- a citation marker that appears where it actually
 * occurs in the sentence, not bolted on below it. Falls back to plain text
 * when there is nothing to interleave (no citations for this message, or a
 * message reloaded from a session where only bare marker strings persist
 * -- see the citationsByMessageId note above). */
function CitedText({ text, citations }: { text: string; citations?: SseCitationEvent[] }) {
  const markers = (citations ?? []).map((c) => c.marker).filter(Boolean);
  if (markers.length === 0) return <>{text}</>;

  const escaped = [...new Set(markers)].sort((a, b) => b.length - a.length).map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "g"));
  const byMarker = new Map((citations ?? []).map((c) => [c.marker, c]));

  return (
    <>
      {parts.map((part, i) => {
        const citation = byMarker.get(part);
        return citation ? <CitationMark key={i} citation={citation} /> : <span key={i}>{part}</span>;
      })}
    </>
  );
}

function CitationMark({ citation }: { citation: SseCitationEvent }) {
  return (
    <span className="group relative inline-block not-italic">
      <button
        type="button"
        className="mx-0.5 rounded-xs border border-accent bg-accent-wash px-1 align-text-top font-mono text-[0.6875rem] font-medium text-accent-strong transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus-ring)]"
      >
        {citation.marker}
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 w-64 -translate-x-1/2 border border-border-strong bg-surface-raised p-2.5 text-left text-xs normal-case text-ink opacity-0 shadow-[0_8px_24px_rgb(var(--shadow-color)/0.16)] transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100"
      >
        <span className="block italic text-ink-muted">&ldquo;{citation.quote}&rdquo;</span>
        {citation.section && (
          <span className="mt-1 block text-ink-subtle">
            {citation.section}
            {citation.page != null ? `, p.${citation.page}` : ""}
          </span>
        )}
      </span>
    </span>
  );
}

function MessageBubble({
  message,
  citations,
  meta,
}: {
  message: ChatMessage;
  citations?: SseCitationEvent[];
  meta?: { suggestion?: string | null; unsupportedDropped?: number };
}) {
  const isUser = message.role === "user";
  // An unanswerable turn has no generated text at all (the backend skips
  // generation once it decides there isn't enough grounding) -- showing an
  // empty bubble would read as broken, not as an honest "no" the product's
  // own degrade-honestly principle calls for.
  const bodyText =
    !isUser && !message.answerable
      ? (meta?.suggestion ?? "This can't be answered from the current workspace papers.")
      : message.content;
  return (
    <div className={isUser ? "ml-8" : "mr-8"}>
      <Card className={isUser ? "bg-accent-wash" : ""}>
        <CardBody>
          <p className="max-w-[70ch] whitespace-pre-wrap text-sm text-ink">
            <CitedText text={bodyText} citations={citations} />
          </p>
          {!isUser &&
            (message.faithfulness != null ||
              !message.answerable ||
              (meta?.unsupportedDropped ?? 0) > 0 ||
              (!citations && message.citations.length > 0)) && (
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[0.6875rem] text-ink-subtle">
              {message.faithfulness != null && (
                <span className={message.faithfulness >= 0.8 ? "text-verified" : message.faithfulness >= 0.5 ? "text-warning" : "text-danger"}>
                  faithfulness {message.faithfulness.toFixed(2)}
                </span>
              )}
              {!message.answerable && <span className="text-warning">not answerable from workspace</span>}
              {(meta?.unsupportedDropped ?? 0) > 0 && (
                <span className="text-warning">
                  {meta!.unsupportedDropped} unsupported claim{meta!.unsupportedDropped === 1 ? "" : "s"} dropped
                </span>
              )}
              {!citations && message.citations.length > 0 && (
                <span>{message.citations.length} citation{message.citations.length === 1 ? "" : "s"} (quote detail not saved for past sessions)</span>
              )}
            </p>
          )}
          {!isUser && message.claims && message.claims.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer list-none text-xs text-ink-subtle hover:text-ink-muted">
                View {message.claims.length} claim{message.claims.length === 1 ? "" : "s"}
              </summary>
              <ul className="mt-1 space-y-1.5">
                {message.claims.map((c) => (
                  <li key={c.claim_id} className="rule-t bg-surface-sunken px-2.5 py-1.5 text-xs text-ink-muted">
                    <span className={c.is_supported ? "" : "text-warning"}>{c.sentence}</span>
                    {c.supporting_paper_ids.length > 0 && (
                      <span className="ml-1.5 font-mono text-ink-subtle">[{c.supporting_paper_ids.join(", ")}]</span>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
