"use client";

import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { ArrowSquareOut, Check, Eye, EyeSlash, Star, Warning } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { llmKeys, workspaces as workspacesApi } from "@/lib/api/endpoints";
import type { LlmProvider, Workspace } from "@/lib/api/types";
import { Timestamp } from "@/components/ui/Timestamp";
import { PROVIDERS, STATUS_COPY, describeTest, maskedKey, type ProviderRow } from "@/lib/settings";
import { C, InlineError, focusRing, primaryButton, quietButton } from "@/components/cinematic/ui";

export function Section({ id, title, lead, children }: { id: string; title: string; lead: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-24 border-t pt-8 first:border-t-0 first:pt-0" style={{ borderColor: C.line }}>
      <h2 id={`${id}-title`} className="text-[20px] font-bold tracking-[-0.01em]">
        {title}
      </h2>
      <p className="mt-1.5 max-w-[68ch] text-[14px] leading-relaxed" style={{ color: C.muted }}>
        {lead}
      </p>
      <div className="mt-5">{children}</div>
    </section>
  );
}

export function SmallButton({
  children,
  onClick,
  disabled,
  pressed,
  tone = "quiet",
  label,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  pressed?: boolean;
  tone?: "quiet" | "danger" | "primary";
  label?: string;
}) {
  const style =
    tone === "primary"
      ? primaryButton
      : tone === "danger"
        ? { background: "rgba(255,155,155,.08)", border: "1px solid rgba(255,155,155,.4)", color: C.danger }
        : pressed
          ? { background: "rgba(93,240,168,.14)", border: "1px solid rgba(93,240,168,.45)", color: C.ink }
          : { ...quietButton, color: C.ink };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={pressed}
      aria-label={label}
      className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-[opacity,background-color,transform] active:scale-[0.97] disabled:opacity-45 sm:min-h-9 ${tone === "quiet" && !pressed ? "hover:bg-white/10" : ""} ${focusRing}`}
      style={style}
    >
      {children}
    </button>
  );
}

function StatusMark({ status }: { status: ProviderRow["status"] }) {
  const color = status === "working" ? C.mint : status === "failed" ? C.danger : C.muted;
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px]" style={{ color }}>
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden className="shrink-0">
        {status === "working" ? (
          <circle cx="5" cy="5" r="4" fill={color} />
        ) : status === "failed" ? (
          <path d="M2 2l6 6M8 2l-6 6" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
        ) : status === "unverified" ? (
          <circle cx="5" cy="5" r="3.6" fill="none" stroke={color} strokeWidth="1.4" strokeDasharray="2 1.6" />
        ) : (
          <circle cx="5" cy="5" r="3.6" fill="none" stroke={color} strokeWidth="1.2" opacity="0.6" />
        )}
      </svg>
      {STATUS_COPY[status]}
    </span>
  );
}

/** One provider: its saved key (only the last four characters), its status and what can be done with it. */
export function ProviderLine({
  row,
  onDefault,
  onCheck,
  onReplace,
  onRemove,
  busy,
  note,
}: {
  row: ProviderRow;
  onDefault: () => void;
  onCheck: () => void;
  onReplace: () => void;
  onRemove: () => void;
  busy: boolean;
  note: { ok: boolean; text: string } | null;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="px-4 py-3.5" data-testid={`provider-${row.id}`}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-[160px] flex-1">
          <p className="flex items-center gap-2 text-[15px] font-semibold">
            {row.name}
            {row.isActive && (
              <span className="text-[12.5px] font-semibold" style={{ color: C.mint }}>
                · in use
              </span>
            )}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
            <StatusMark status={row.status} />
            {row.key && (
              <>
                <span className="font-mono text-[12.5px] tabular-nums" style={{ color: C.muted }} aria-label={`key ending ${row.key.key_last4}`}>
                  {maskedKey(row.key.key_last4)}
                </span>
                {row.key.checked_at && (
                  <span className="text-[12.5px]" style={{ color: C.muted }}>
                    checked <Timestamp at={row.key.checked_at} />
                  </span>
                )}
              </>
            )}
          </p>
        </div>
        {row.key ? (
          confirming ? (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Remove the ${row.name} key?`}>
              <span className="text-[13px]" style={{ color: C.muted }}>
                Remove this key?
              </span>
              <SmallButton tone="danger" disabled={busy} onClick={() => { setConfirming(false); onRemove(); }}>
                Remove
              </SmallButton>
              <SmallButton onClick={() => setConfirming(false)}>Keep it</SmallButton>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <SmallButton pressed={row.isDefault} disabled={busy} onClick={onDefault} label={row.isDefault ? `${row.name} is your default; clear it` : `Make ${row.name} the default`}>
                <Star className="size-3.5" weight={row.isDefault ? "fill" : "regular"} aria-hidden />
                {row.isDefault ? "Default" : "Make default"}
              </SmallButton>
              <SmallButton disabled={busy} onClick={onCheck} label={`Check the ${row.name} key again`}>
                Check again
              </SmallButton>
              <SmallButton disabled={busy} onClick={onReplace} label={`Replace the ${row.name} key`}>
                Replace
              </SmallButton>
              <SmallButton disabled={busy} onClick={() => setConfirming(true)} label={`Remove the ${row.name} key`}>
                Remove
              </SmallButton>
            </div>
          )
        ) : (
          <SmallButton onClick={onReplace} label={`Add a ${row.name} key`}>
            Add a key
          </SmallButton>
        )}
      </div>
      {note && (
        <p className="mt-2 text-[13px] leading-snug" style={{ color: note.ok ? C.mint : C.danger }} role="status">
          {note.text}
        </p>
      )}
    </li>
  );
}

/** Adding or replacing a key: tested first, sent once, stored encrypted, never shown again. */
export function KeyForm({
  provider,
  onProvider,
  inputRef,
  onSaved,
}: {
  provider: LlmProvider;
  onProvider: (p: LlmProvider) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onSaved: () => void;
}) {
  const id = useId();
  const [value, setValue] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);
  const name = PROVIDERS.find((p) => p.id === provider)?.name ?? provider;

  // no ApiError means no readable answer at all: the server is down or crashed -- not a problem with the key
  const failure = (e: unknown, doing: "test" | "save") =>
    e instanceof ApiError
      ? e.message
      : `Couldn't reach the server to ${doing} this key. Check that the backend is running on port 8000, then try again.`;

  async function test() {
    setBusy("test");
    setOutcome(null);
    try {
      const result = await llmKeys.test(provider, value.trim());
      setOutcome({ ok: result.success, text: `${describeTest(result)} Not saved yet.` });
    } catch (e) {
      setOutcome({ ok: false, text: failure(e, "test") });
    } finally {
      setBusy(null);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy("save");
    setOutcome(null);
    try {
      const saved = await llmKeys.save(provider, value.trim());
      setValue(""); // the key leaves the page as soon as it is stored
      setReveal(false);
      const text =
        saved.status === "working"
          ? `Saved. The ${name} key works, and it is stored encrypted.`
          : `Saved, but the ${name} key failed its check, so it won't be used until it works.`;
      setOutcome({ ok: saved.status === "working", text }); // its role="status" announces it
      onSaved();
    } catch (err) {
      setOutcome({ ok: false, text: failure(err, "save") });
    } finally {
      setBusy(null);
    }
  }

  return (
    <form onSubmit={save} className="rounded-2xl p-4 sm:p-5" style={{ background: "rgba(255,255,255,.025)", border: `1px solid ${C.line}` }} aria-labelledby={`${id}-t`}>
      <h3 id={`${id}-t`} className="text-[15px] font-bold">
        Add or replace a key
      </h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)]">
        <div>
          <label htmlFor={`${id}-provider`} className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
            Provider
          </label>
          <select
            id={`${id}-provider`}
            value={provider}
            onChange={(e) => {
              onProvider(e.target.value as LlmProvider);
              setOutcome(null);
            }}
            className={`mt-1 min-h-11 w-full rounded-xl bg-transparent px-3 text-[14px] [color-scheme:dark] ${focusRing}`}
            style={{ ...quietButton, color: C.ink }}
          >
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-key`} className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
            API key
          </label>
          <div className="relative mt-1 flex items-center">
            <input
              id={`${id}-key`}
              ref={inputRef}
              type={reveal ? "text" : "password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              autoCapitalize="off"
              data-1p-ignore
              data-lpignore="true"
              placeholder={`Paste a ${name} key`}
              className={`min-h-11 w-full rounded-xl bg-transparent pl-3 pr-12 font-mono text-[13.5px] caret-[#5df0a8] outline-none placeholder:font-sans placeholder:text-[#8f9bb8] ${focusRing}`}
              style={{ ...quietButton, color: C.ink }}
            />
            <button
              type="button"
              onClick={() => setReveal((r) => !r)}
              aria-label={reveal ? "Hide the key" : "Show the key"}
              aria-pressed={reveal}
              className={`absolute right-1 inline-flex size-10 items-center justify-center rounded-lg hover:bg-white/10 ${focusRing}`}
              style={{ color: C.muted }}
            >
              {reveal ? <EyeSlash className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            </button>
          </div>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={!value.trim() || busy != null}
          className={`inline-flex min-h-11 items-center rounded-full px-5 text-sm font-semibold transition-[opacity,transform] active:scale-[0.97] disabled:opacity-45 ${focusRing}`}
          style={primaryButton}
        >
          {busy === "save" ? "Testing and saving…" : "Save key"}
        </button>
        <SmallButton disabled={!value.trim() || busy != null} onClick={test}>
          {busy === "test" ? "Testing…" : "Test without saving"}
        </SmallButton>
      </div>
      {outcome && (
        <p className="mt-3 flex items-start gap-1.5 text-[13.5px] leading-snug" style={{ color: outcome.ok ? C.mint : C.danger }} role="status">
          {outcome.ok ? <Check className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden /> : <Warning className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden />}
          {outcome.text}
        </p>
      )}
      <p className="mt-4 text-[12.5px] leading-relaxed" style={{ color: C.muted }}>
        The key is sent once, to this server, which tests it with {name} and stores it encrypted. Only its last four characters are ever shown again,
        and it never leaves the server.
      </p>
    </form>
  );
}

/** A workspace's name, editable in place. */
export function WorkspaceRow({ ws, onSaved, extra }: { ws: Workspace; onSaved: () => void; extra?: ReactNode }) {
  const [title, setTitle] = useState(ws.title);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const changed = title.trim() !== ws.title;
  const titleId = useId();
  const saving = useRef(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (saving.current || !changed || !title.trim()) return;
    saving.current = true;
    setBusy(true);
    setNote(null);
    try {
      await workspacesApi.update(ws.workspace_id, { title: title.trim() });
      setNote({ ok: true, text: "Saved." });
      onSaved();
    } catch {
      setNote({ ok: false, text: "That wasn't saved. Try again." });
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return (
    <li className="px-4 py-4" data-testid={`workspace-${ws.workspace_id}`}>
      <form onSubmit={save} className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <label htmlFor={titleId} className="block min-w-0">
          <span className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
            Name
          </span>
          <input
            id={titleId}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            className={`mt-1 min-h-11 w-full rounded-xl bg-transparent px-3 text-[14px] caret-[#5df0a8] outline-none ${focusRing}`}
            style={{ ...quietButton, color: C.ink }}
          />
        </label>
        <button
          type="submit"
          disabled={!changed || busy || !title.trim()}
          className={`inline-flex min-h-11 items-center justify-center rounded-full px-4 text-sm font-semibold transition-[opacity,background-color] hover:bg-white/10 disabled:opacity-45 ${focusRing}`}
          style={{ ...quietButton, color: C.ink }}
        >
          {busy ? "Saving…" : "Save"}
        </button>
      </form>
      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-[13px]">
        <span style={{ color: C.muted }}>
          <span className="tabular-nums">{ws.papers.length}</span> paper{ws.papers.length === 1 ? "" : "s"} · created <Timestamp at={ws.created_at} style="date" />
        </span>
        <span className="flex items-center gap-3">
          <Link
            href={`/workspace/${ws.workspace_id}`}
            className={`inline-flex min-h-11 items-center gap-1 rounded-sm text-[13px] hover:text-white sm:min-h-0 ${focusRing}`}
            style={{ color: C.muted }}
          >
            Open workspace
            <ArrowSquareOut className="size-3.5" aria-hidden />
          </Link>
          {extra}
        </span>
      </div>
      {note && (
        <p className="mt-2 text-[13px]" style={{ color: note.ok ? C.mint : C.danger }} role="status">
          {note.text}
        </p>
      )}
    </li>
  );
}

export function LoadFailure({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className="rounded-2xl p-5" style={{ background: C.glass, border: `1px solid ${C.line}` }}>
      <InlineError message={`Could not load ${what}.`} />
      <button type="button" onClick={onRetry} className={`mt-3 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={primaryButton}>
        Try again
      </button>
    </div>
  );
}
