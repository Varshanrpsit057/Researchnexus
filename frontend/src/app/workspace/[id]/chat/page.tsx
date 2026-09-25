"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { ArrowLeft, ChatsCircle, PaperPlaneTilt, Plus, Stop, Warning } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { papers as papersApi, workspaces } from "@/lib/api/endpoints";
import { streamChat } from "@/lib/api/chat-stream";
import type { ChatMessage, ChatSession, RagStage } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { citationFromEvent, citationsIn, errorCopy, relativeTime, segmentAnswer, type Citation, type Segment } from "@/lib/chat";
import { CinematicHeader } from "@/components/layout/CinematicHeader";
import { C, InlineError, WorkspaceLoadError, focusRing, primaryButton, quietButton } from "../ui";
import { AnswerText, EvidencePanel, OutcomeNotes, SourceRow, StageTrail, type PaperKind } from "./parts";
import styles from "./chat.module.css";

interface Live {
  question: string;
  regenerate: boolean;
  stage: RagStage | null;
  seen: RagStage[];
  segments: Segment[];
  error: { code?: string; message: string } | null;
}

interface Inspecting {
  messageId: string;
  claimId: string;
}

const LIVE_ID = "live";

function appendText(segments: Segment[], text: string): Segment[] {
  const last = segments.at(-1);
  if (last?.kind === "text") return [...segments.slice(0, -1), { kind: "text", text: last.text + text }];
  return [...segments, { kind: "text", text }];
}

export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const { me } = useAuth();
  const router = useRouter();
  const sessionId = useSearchParams().get("session");
  const { mutate: mutateGlobal } = useSWRConfig();

  const workspaceQ = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));
  const sessionsQ = useSWR(ready && workspaceQ.data ? ["ws-chat-sessions", id] : null, () => workspaces.chatSessions(id));
  const threadKey = sessionId ? ["chat-session", id, sessionId] : null;
  const threadQ = useSWR(ready && workspaceQ.data ? threadKey : null, () => workspaces.chatSession(id, sessionId!));

  const [live, setLive] = useState<Live | null>(null);
  const [draft, setDraft] = useState("");
  const [inspecting, setInspecting] = useState<Inspecting | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [showConversations, setShowConversations] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const workspace = workspaceQ.data;
  // the seed's title (shared cache with the overview and the trail)
  const seedQ = useSWR(workspace ? ["paper", workspace.seed_paper_id] : null, () => papersApi.get(workspace!.seed_paper_id));
  const messages = useMemo(() => threadQ.data?.messages ?? [], [threadQ.data]);
  const streaming = live != null && live.error == null;
  const noKey = me != null && !me.has_working_llm_key;

  const kindOf = useCallback(
    (paperId: string): PaperKind =>
      paperId === workspace?.seed_paper_id ? "seed" : workspace?.papers.some((p) => p.paper_id === paperId) ? "member" : "connected",
    [workspace],
  );

  // every answer as prose + inline citations, stored or live
  const answers = useMemo(() => {
    const map = new Map<string, Segment[]>();
    for (const m of messages) if (m.role === "assistant") map.set(m.message_id, segmentAnswer(m.content, m.claims ?? []));
    if (live) map.set(LIVE_ID, live.segments);
    return map;
  }, [messages, live]);

  const inspected: Citation | null = useMemo(() => {
    if (!inspecting) return null;
    return citationsIn(answers.get(inspecting.messageId) ?? []).find((c) => c.claimId === inspecting.claimId) ?? null;
  }, [inspecting, answers]);
  const inspectedTotal = inspecting ? citationsIn(answers.get(inspecting.messageId) ?? []).length : 0;

  // the newest turn stays in view as it is written
  const liveLength = live ? live.segments.reduce((n, s) => n + (s.kind === "text" ? s.text.length : 1), 0) : 0;
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: liveLength > 0 ? "auto" : "smooth" });
  }, [messages.length, live?.stage, liveLength, live?.error]);

  function openSession(next: string | null) {
    abortRef.current?.abort();
    setLive(null);
    setInspecting(null);
    setShowConversations(false);
    router.replace(next ? `/workspace/${id}/chat?session=${encodeURIComponent(next)}` : `/workspace/${id}/chat`, { scroll: false });
    if (!next) requestAnimationFrame(() => inputRef.current?.focus());
  }

  async function ask(question: string, regenerate = false) {
    if (!question.trim() || streaming) return;
    setInspecting(null);
    setLive({ question, regenerate, stage: null, seen: [], segments: [], error: null });
    setAnnouncement(regenerate ? "Answering the question again." : "Question sent.");
    const controller = new AbortController();
    abortRef.current = controller;
    const fail = (message: string, code?: string) => setLive((l) => l && { ...l, error: { code, message: errorCopy(code, message) } });
    try {
      await streamChat(
        id,
        { message: regenerate ? "" : question, session_id: sessionId, regenerate },
        {
          onStatus: ({ stage }) => setLive((l) => l && { ...l, stage, seen: l.seen.includes(stage) ? l.seen : [...l.seen, stage] }),
          onToken: (text) => setLive((l) => l && { ...l, segments: appendText(l.segments, text) }),
          onCitation: (event) => setLive((l) => l && { ...l, segments: [...l.segments, { kind: "cite", citation: citationFromEvent(event) }] }),
          onError: fail,
          onDone: (done) => {
            // show the stored turn before the live one goes, so nothing flickers
            void (async () => {
              const key = ["chat-session", id, done.session_id];
              await mutateGlobal(key, workspaces.chatSession(id, done.session_id), { revalidate: false });
              void sessionsQ.mutate();
              if (done.session_id !== sessionId) {
                router.replace(`/workspace/${id}/chat?session=${encodeURIComponent(done.session_id)}`, { scroll: false });
              }
              setLive(null);
              setAnnouncement(done.answerable ? "Answer ready. Its sources are listed below it." : "This workspace can't answer that question.");
            })();
          },
        },
        controller.signal,
      );
    } catch (e) {
      if (controller.signal.aborted) return;
      if (e instanceof ApiError) fail(e.message, e.code);
      else fail("", "network");
    }
  }

  function stop() {
    abortRef.current?.abort();
    setLive(null);
    // an answer that was already written is stored; show whatever landed
    void threadQ.mutate();
    void sessionsQ.mutate();
    setAnnouncement("Stopped.");
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const question = draft.trim();
    if (!question) return;
    setDraft("");
    void ask(question);
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const lastQuestion = [...messages].reverse().find((m) => m.role === "user")?.content;
  // while an answer is regenerated, the one it replaces steps aside
  const shown = live?.regenerate && lastAssistant ? messages.filter((m) => m.message_id !== lastAssistant.message_id) : messages;
  const conversations = sessionsQ.data?.sessions ?? [];

  if (!ready) return null;
  if (workspaceQ.error) {
    return (
      <Shell>
        <div className="px-4">
          <WorkspaceLoadError error={workspaceQ.error} onRetry={() => workspaceQ.mutate()} />
        </div>
      </Shell>
    );
  }

  const conversationList = (
    <ConversationList
      sessions={conversations}
      loading={!sessionsQ.data && !sessionsQ.error}
      failed={Boolean(sessionsQ.error)}
      activeId={sessionId}
      onRetry={() => sessionsQ.mutate()}
      onOpen={openSession}
    />
  );

  return (
    <Shell>
      <div className="mx-auto flex min-h-0 w-full max-w-[1480px] flex-1 gap-6 px-4 sm:px-6">
        {/* conversations: a column on wide screens */}
        <nav aria-label="Conversations" className="hidden w-64 shrink-0 flex-col pt-6 lg:flex">
          <NewConversation onClick={() => openSession(null)} />
          <div className="mt-4 min-h-0 flex-1 overflow-y-auto pb-6 [scrollbar-color:rgba(150,175,230,.28)_transparent]">{conversationList}</div>
        </nav>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 pt-5 lg:pt-6">
            <div className="min-w-0 flex-1">
              {workspace ? (
                <Link
                  href={`/workspace/${id}`}
                  className={`inline-flex min-h-11 max-w-full items-center gap-1.5 rounded-sm text-sm hover:text-white sm:min-h-0 ${focusRing}`}
                  style={{ color: C.muted }}
                >
                  <ArrowLeft className="size-4 shrink-0" aria-hidden />
                  <span className="truncate">{workspace.title}</span>
                </Link>
              ) : (
                <div className="h-5 w-48 rounded motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.08)" }} />
              )}
              <h1 className="mt-1.5 text-[clamp(24px,3vw,32px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Ask this workspace</h1>
            </div>
            <div className="flex items-center gap-2 lg:hidden">
              <button
                type="button"
                onClick={() => setShowConversations((v) => !v)}
                aria-expanded={showConversations}
                aria-controls="chat-conversations-sheet"
                className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold ${focusRing}`}
                style={quietButton}
              >
                <ChatsCircle className="size-4" aria-hidden />
                Conversations{conversations.length > 0 && <span className="tabular-nums" style={{ color: C.muted }}>{conversations.length}</span>}
              </button>
              <NewConversation compact onClick={() => openSession(null)} />
            </div>
          </header>

          {showConversations && (
            <div id="chat-conversations-sheet" className="mt-3 max-h-[50dvh] overflow-y-auto rounded-2xl p-3 lg:hidden" style={{ background: "rgba(10,15,32,.92)", border: `1px solid ${C.lineStrong}` }}>
              {conversationList}
            </div>
          )}

          <p className="sr-only" aria-live="polite">
            {announcement}
          </p>

          {/* the thread */}
          <div className="relative mt-4 min-h-0 flex-1 overflow-y-auto [scrollbar-color:rgba(150,175,230,.28)_transparent]" data-testid="chat-thread">
            <div className="mx-auto max-w-[760px] space-y-8 pb-8">
              {sessionId && threadQ.error ? (
                <div className="rounded-2xl px-5 py-6" style={{ background: C.glass, border: `1px dashed ${C.lineStrong}` }}>
                  <InlineError
                    message={
                      threadQ.error instanceof ApiError && threadQ.error.status === 404
                        ? "That conversation isn't in this workspace anymore."
                        : "Could not load this conversation."
                    }
                  />
                  <div className="mt-4 flex gap-2">
                    {!(threadQ.error instanceof ApiError && threadQ.error.status === 404) && (
                      <button type="button" onClick={() => threadQ.mutate()} className={`rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                        Try again
                      </button>
                    )}
                    <button type="button" onClick={() => openSession(null)} className={`rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={quietButton}>
                      Start a new conversation
                    </button>
                  </div>
                </div>
              ) : sessionId && !threadQ.data ? (
                <div role="status" className="space-y-6">
                  <span className="sr-only">Loading the conversation…</span>
                  <div className="ml-auto h-12 w-2/3 rounded-2xl motion-safe:animate-pulse" style={{ background: C.glass }} />
                  <div className="h-28 w-full rounded-2xl motion-safe:animate-pulse" style={{ background: C.glass }} />
                </div>
              ) : shown.length === 0 && !live ? (
                <Welcome
                  paperCount={workspace?.papers.length ?? 0}
                  seedTitle={seedQ.data?.title ?? null}
                  disabled={noKey}
                  onPick={(q) => {
                    setDraft(q);
                    inputRef.current?.focus();
                  }}
                />
              ) : null}

              {shown.map((m) =>
                m.role === "user" ? (
                  <Question key={m.message_id} text={m.content} />
                ) : (
                  <Answer
                    key={m.message_id}
                    message={m}
                    segments={answers.get(m.message_id) ?? []}
                    lit={inspecting?.messageId === m.message_id ? inspecting.claimId : hovered}
                    kindOf={kindOf}
                    workspaceId={id}
                    onOpen={(c) => setInspecting({ messageId: m.message_id, claimId: c.claimId })}
                    onHover={setHovered}
                    onRegenerate={m.message_id === lastAssistant?.message_id && !noKey && lastQuestion ? () => ask(lastQuestion, true) : undefined}
                    busy={streaming}
                  />
                ),
              )}

              {live && (
                <>
                  {!live.regenerate && <Question text={live.question} />}
                  <section aria-label="Answer being written" className={styles.enter}>
                    {live.error ? (
                      <div className="rounded-2xl px-5 py-4" style={{ background: "rgba(255,155,155,.06)", border: "1px solid rgba(255,155,155,.25)" }}>
                        <InlineError message={live.error.message} />
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          {live.error.code === "llm_key_required" ? (
                            <Link href="/settings" className={`rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                              Add a key in Settings
                            </Link>
                          ) : (
                            <button type="button" onClick={() => ask(live.question, live.regenerate)} className={`rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                              Try again
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => {
                              if (!live.regenerate) setDraft(live.question);
                              setLive(null);
                              inputRef.current?.focus();
                            }}
                            className={`rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`}
                            style={quietButton}
                          >
                            {live.regenerate ? "Dismiss" : "Edit the question"}
                          </button>
                        </div>
                      </div>
                    ) : live.segments.length === 0 ? (
                      <StageTrail stage={live.stage} seen={live.seen} />
                    ) : (
                      <AnswerText
                        segments={live.segments}
                        lit={inspecting?.messageId === LIVE_ID ? inspecting.claimId : hovered}
                        caret
                        onOpen={(c) => setInspecting({ messageId: LIVE_ID, claimId: c.claimId })}
                        onHover={setHovered}
                      />
                    )}
                  </section>
                </>
              )}
              <div ref={endRef} />
            </div>
          </div>

          {/* the composer */}
          <form onSubmit={submit} className="mx-auto w-full max-w-[760px] shrink-0 pb-4 pt-2 sm:pb-6">
            {noKey && (
              <p className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]" style={{ color: C.warning }}>
                <Warning className="size-4 shrink-0" weight="bold" aria-hidden />
                No working LLM provider key is saved, so questions can&apos;t be answered yet.
                <Link href="/settings" className={`rounded-sm font-semibold underline underline-offset-4 ${focusRing}`}>
                  Add a key
                </Link>
              </p>
            )}
            <div
              className="flex items-end gap-2 rounded-[22px] p-2 pl-4 backdrop-blur-md focus-within:border-[rgba(93,240,168,.55)]"
              style={{ background: "rgba(10,15,32,.82)", border: `1px solid ${C.lineStrong}` }}
            >
              <label htmlFor="chat-question" className="sr-only">
                Ask a question about this workspace&apos;s papers
              </label>
              <textarea
                id="chat-question"
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    if (!streaming) submit(e as unknown as FormEvent);
                  }
                }}
                rows={1}
                disabled={noKey}
                placeholder={noKey ? "Add an LLM key in Settings to ask questions" : "Ask about these papers…"}
                className="max-h-40 min-h-11 flex-1 resize-none bg-transparent py-2.5 text-[15px] leading-snug caret-[#5df0a8] outline-none placeholder:text-[#8f9bb8] disabled:cursor-not-allowed [field-sizing:content]"
                style={{ color: C.ink }}
              />
              {streaming ? (
                <button
                  type="button"
                  onClick={stop}
                  aria-label="Stop answering"
                  className={`inline-flex size-11 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-white/10 ${focusRing}`}
                  style={quietButton}
                >
                  <Stop className="size-4" weight="fill" aria-hidden />
                </button>
              ) : (
                <button
                  type="submit"
                  aria-label="Ask"
                  disabled={!draft.trim() || noKey}
                  className={`inline-flex size-11 shrink-0 items-center justify-center rounded-full transition-[opacity,transform] active:scale-[0.96] disabled:opacity-40 ${focusRing}`}
                  style={primaryButton}
                >
                  <PaperPlaneTilt className="size-[18px]" weight="fill" aria-hidden />
                </button>
              )}
            </div>
            <p className="mt-2 hidden text-center text-[12px] sm:block" style={{ color: C.muted2 }}>
              Answers come only from this workspace&apos;s papers. Every sentence is checked against the passage it cites.
            </p>
          </form>
        </div>

        {/* the evidence behind one cited sentence */}
        {inspected && inspecting && (
          <div className="fixed inset-x-2 bottom-2 z-30 flex max-h-[62dvh] lg:static lg:inset-auto lg:z-auto lg:max-h-none lg:w-[380px] lg:shrink-0 lg:py-6">
            <div className="flex min-h-0 w-full flex-col">
              <EvidencePanel
                citation={inspected}
                total={inspectedTotal}
                workspaceId={id}
                kindOf={kindOf}
                onStep={(d) => {
                  const list = citationsIn(answers.get(inspecting.messageId) ?? []);
                  const next = list.find((c) => c.marker === inspected.marker + d);
                  if (next) setInspecting({ ...inspecting, claimId: next.claimId });
                }}
                onClose={() => setInspecting(null)}
              />
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}

/** Header over a full-height column; a denser scrim than the graph, since this is reading. */
function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex h-dvh flex-col overflow-hidden selection:bg-[rgba(93,240,168,0.28)] selection:text-white" style={{ color: C.ink }}>
      <div
        className="pointer-events-none fixed inset-0 -z-10"
        style={{ background: "linear-gradient(180deg, rgba(4,6,15,.6) 0%, rgba(4,6,15,.84) 280px, rgba(4,6,15,.9) 100%)" }}
      />
      <CinematicHeader />
      <main id="main" className="relative flex min-h-0 flex-1 flex-col">
        {children}
      </main>
    </div>
  );
}

function NewConversation({ onClick, compact }: { onClick: () => void; compact?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={compact ? "New conversation" : undefined}
      className={`inline-flex min-h-11 items-center justify-center gap-1.5 rounded-full text-[13px] font-semibold transition-colors hover:bg-white/10 ${compact ? "w-11" : "px-4"} ${focusRing}`}
      style={quietButton}
    >
      <Plus className="size-4" weight="bold" aria-hidden />
      {!compact && "New conversation"}
    </button>
  );
}

function ConversationList({
  sessions,
  loading,
  failed,
  activeId,
  onRetry,
  onOpen,
}: {
  sessions: ChatSession[];
  loading: boolean;
  failed: boolean;
  activeId: string | null;
  onRetry: () => void;
  onOpen: (id: string) => void;
}) {
  if (failed) {
    return (
      <div className="px-1">
        <InlineError message="Could not load the conversations." />
        <button type="button" onClick={onRetry} className={`mt-2 min-h-11 text-[13px] underline underline-offset-4 hover:text-white ${focusRing}`} style={{ color: C.muted }}>
          Try again
        </button>
      </div>
    );
  }
  if (loading) {
    return (
      <div role="status" className="space-y-2">
        <span className="sr-only">Loading conversations…</span>
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 rounded-xl motion-safe:animate-pulse" style={{ background: C.glass }} />
        ))}
      </div>
    );
  }
  if (sessions.length === 0) {
    return (
      <p className="px-1 text-[13px] leading-relaxed" style={{ color: C.muted }}>
        Past conversations appear here, each kept with the sources its answers cited.
      </p>
    );
  }
  return (
    <ul className="space-y-1">
      {sessions.map((s) => {
        const on = s.session_id === activeId;
        return (
          <li key={s.session_id}>
            <button
              type="button"
              onClick={() => onOpen(s.session_id)}
              aria-current={on ? "true" : undefined}
              className={`w-full rounded-xl px-3 py-2.5 text-left transition-colors ${on ? "" : "hover:bg-white/[0.05]"} ${focusRing}`}
              style={on ? { background: "rgba(93,240,168,.1)", border: "1px solid rgba(93,240,168,.3)" } : { border: "1px solid transparent" }}
            >
              <span className="line-clamp-2 text-sm font-medium leading-snug">{s.title ?? "Untitled conversation"}</span>
              <span className="mt-0.5 block text-[12px] tabular-nums" style={{ color: C.muted }}>
                {s.questions != null && `${s.questions} question${s.questions === 1 ? "" : "s"} · `}
                {relativeTime(s.last_active_at ?? s.created_at)}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function Question({ text }: { text: string }) {
  return (
    <div className={`flex justify-end ${styles.enter}`}>
      <p
        className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md px-4 py-2.5 text-[15px] leading-relaxed"
        style={{ background: "rgba(93,240,168,.1)", border: "1px solid rgba(93,240,168,.22)" }}
      >
        {text}
      </p>
    </div>
  );
}

function Answer({
  message,
  segments,
  lit,
  kindOf,
  workspaceId,
  onOpen,
  onHover,
  onRegenerate,
  busy,
}: {
  message: ChatMessage;
  segments: Segment[];
  lit: string | null;
  kindOf: (paperId: string) => PaperKind;
  workspaceId: string;
  onOpen: (c: Citation) => void;
  onHover: (claimId: string | null) => void;
  onRegenerate?: () => void;
  busy: boolean;
}) {
  if (!message.answerable) {
    return (
      <section aria-label="Answer" className="rounded-2xl px-5 py-4" style={{ background: "rgba(232,193,92,.06)", border: "1px solid rgba(232,193,92,.22)" }}>
        <p className="font-semibold">This workspace doesn&apos;t hold enough to answer that.</p>
        <p className="mt-1 max-w-[68ch] text-sm leading-relaxed" style={{ color: C.muted }}>
          {message.suggestion ?? "No passage in its papers covers the question well enough to answer it without guessing."}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link href={`/workspace/${workspaceId}#papers`} className={`inline-flex min-h-11 items-center rounded-full px-4 text-[13px] font-semibold sm:min-h-9 ${focusRing}`} style={quietButton}>
            Add papers to this workspace
          </Link>
          {onRegenerate && (
            <button type="button" onClick={onRegenerate} disabled={busy} className={`inline-flex min-h-11 items-center rounded-full px-4 text-[13px] font-semibold disabled:opacity-50 sm:min-h-9 ${focusRing}`} style={quietButton}>
              Try again
            </button>
          )}
        </div>
      </section>
    );
  }
  return (
    <section aria-label="Answer" className={styles.enter}>
      {segments.length > 0 && <AnswerText segments={segments} lit={lit} onOpen={onOpen} onHover={onHover} />}
      <SourceRow segments={segments} kindOf={kindOf} onOpen={onOpen} />
      <OutcomeNotes
        answerable
        hasText={message.content.trim() !== ""}
        unsupportedDropped={message.unsupported_dropped}
        warnings={message.warnings}
        faithfulness={message.content.trim() ? message.faithfulness : null}
        onRegenerate={onRegenerate}
        busy={busy}
      />
    </section>
  );
}

function Welcome({ paperCount, seedTitle, disabled, onPick }: { paperCount: number; seedTitle: string | null; disabled: boolean; onPick: (q: string) => void }) {
  const starters = [
    seedTitle ? `What problem does ${seedTitle} address, and how?` : "What problem do these papers address?",
    ...(paperCount > 1 ? ["How do these papers' methods differ?"] : []),
    "Which datasets and results do these papers report?",
  ];
  return (
    <div className="pt-[8vh]">
      <h2 className="text-[clamp(20px,2.4vw,26px)] font-bold leading-snug tracking-[-0.015em]">
        Ask anything the {paperCount === 1 ? "paper" : `${paperCount} papers`} in this workspace can answer.
      </h2>
      <p className="mt-2 max-w-[60ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
        Answers are written only from their text. Each sentence cites the passage it rests on; open a citation to read that passage and go to its paper.
      </p>
      <ul className="mt-6 space-y-2">
        {starters.map((q) => (
          <li key={q}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(q)}
              className={`w-full rounded-xl px-4 py-3 text-left text-[15px] transition-colors hover:bg-white/[0.06] disabled:opacity-50 disabled:hover:bg-transparent ${focusRing}`}
              style={{ border: `1px solid ${C.line}` }}
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
