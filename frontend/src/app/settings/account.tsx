"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { CheckCircle, Copy, Desktop, DeviceMobile, SignOut, Warning } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { auth as authApi } from "@/lib/api/endpoints";
import type { AuthSession } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { Timestamp } from "@/components/ui/Timestamp";
import { C, focusRing, panel, primaryButton, quietButton } from "@/components/cinematic/ui";
import { PasswordChecklist, PasswordField, passwordRules } from "@/components/auth/AuthUi";
import { LoadFailure, SmallButton } from "./parts";

type Announce = (text: string) => void;

function Field({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
        {term}
      </dt>
      <dd className="mt-1 text-[14.5px]">{children}</dd>
    </div>
  );
}

function Panel({ title, lead, children }: { title: string; lead?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl p-5" style={panel} aria-label={title}>
      <h3 className="text-[16px] font-bold">{title}</h3>
      {lead && (
        <p className="mt-1 max-w-[68ch] text-[13.5px] leading-relaxed" style={{ color: C.muted }}>
          {lead}
        </p>
      )}
      <div className="mt-4">{children}</div>
    </section>
  );
}

const inputClass = `h-10 w-full rounded-xl px-3.5 text-sm outline-none transition-colors focus:border-[#5df0a8] ${focusRing}`;
const inputStyle = { background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink };

/** "Mozilla/5.0 (Windows NT 10.0; ...) ... Edg/140" -> "Edge on Windows" */
export function deviceName(userAgent: string | null): { label: string; mobile: boolean } {
  const ua = userAgent ?? "";
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /OPR\//.test(ua)
      ? "Opera"
      : /Firefox\//.test(ua)
        ? "Firefox"
        : /Chrome\//.test(ua)
          ? "Chrome"
          : /Safari\//.test(ua)
            ? "Safari"
            : null;
  const os = /Windows/.test(ua)
    ? "Windows"
    : /Android/.test(ua)
      ? "Android"
      : /iPhone|iPad|iPod/.test(ua)
        ? "iOS"
        : /Mac OS X|Macintosh/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : null;
  const mobile = /Android|iPhone|iPad|iPod|Mobile/.test(ua);
  if (browser && os) return { label: `${browser} on ${os}`, mobile };
  return { label: browser ?? os ?? (ua ? "Another app" : "Unknown device"), mobile };
}

export function AccountPane({ onAddKey, announce }: { onAddKey: () => void; announce: Announce }) {
  const { me } = useAuth();
  if (!me) {
    return (
      <div role="status" className="h-28 rounded-2xl motion-safe:animate-pulse" style={panel}>
        <span className="sr-only">Loading your account…</span>
      </div>
    );
  }
  return (
    <div className="space-y-5">
      {!me.has_working_llm_key && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl px-5 py-4" style={{ background: "rgba(232,193,92,.07)", border: "1px solid rgba(232,193,92,.35)" }}>
          <p className="flex items-start gap-2 text-[14px] leading-snug" style={{ color: C.warning }}>
            <Warning className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden />
            No working language model key yet: analysing papers, chat, comparison, gaps and directions need one.
          </p>
          <button type="button" onClick={onAddKey} className={`rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={primaryButton}>
            Add a key
          </button>
        </div>
      )}
      <Profile announce={announce} />
      <ChangePassword announce={announce} />
      <Devices announce={announce} />
    </div>
  );
}

function Profile({ announce }: { announce: Announce }) {
  const { me, refreshMe, signOut } = useAuth();
  const router = useRouter();
  const [name, setName] = useState(me?.name ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!me) return null;
  const changed = name.trim() !== (me.name ?? "") && name.trim().length > 0;

  async function saveName(e: FormEvent) {
    e.preventDefault();
    if (!changed) return;
    setSaving(true);
    setError(null);
    try {
      await authApi.updateMe({ name: name.trim() });
      refreshMe();
      announce("Name saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the name. Try again.");
    } finally {
      setSaving(false);
    }
  }

  async function copyId() {
    try {
      await navigator.clipboard.writeText(me!.id);
      announce("Account ID copied.");
    } catch {
      announce("Couldn't copy; select the ID instead.");
    }
  }

  return (
    <Panel title="Profile">
      <form onSubmit={saveName} className="mb-5 flex max-w-md flex-col gap-1.5">
        <label htmlFor="account-name" className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
          Name
        </label>
        <div className="flex gap-2">
          <input
            id="account-name"
            className={inputClass}
            style={inputStyle}
            value={name}
            maxLength={120}
            autoComplete="name"
            onChange={(e) => setName(e.target.value)}
          />
          <button
            type="submit"
            disabled={!changed || saving}
            className={`shrink-0 rounded-full px-4 text-sm font-semibold disabled:opacity-50 ${focusRing}`}
            style={changed ? primaryButton : { ...quietButton, color: C.ink }}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
        {error && (
          <p role="alert" className="text-[13px]" style={{ color: C.danger }}>
            {error}
          </p>
        )}
      </form>
      <dl className="grid grid-cols-[minmax(0,1fr)] gap-5 sm:grid-cols-2">
        <Field term="Email">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold [overflow-wrap:anywhere]">{me.email}</span>
            {me.email_verified && (
              <span className="inline-flex items-center gap-1 text-[12.5px]" style={{ color: C.mint }}>
                <CheckCircle className="size-3.5" weight="fill" aria-hidden />
                Verified
              </span>
            )}
          </span>
        </Field>
        <Field term="Member since">
          <Timestamp at={me.created_at} style="long" />
        </Field>
        <Field term="Account ID">
          <span className="inline-flex items-center gap-2">
            <span className="font-mono text-[13px] [overflow-wrap:anywhere]" style={{ color: C.muted }}>
              {me.id}
            </span>
            <button
              type="button"
              onClick={copyId}
              aria-label="Copy the account ID"
              className={`inline-flex size-11 items-center justify-center rounded-lg hover:bg-white/10 sm:size-8 ${focusRing}`}
              style={{ color: C.muted }}
            >
              <Copy className="size-4" aria-hidden />
            </button>
          </span>
        </Field>
        <Field term="Sign-in">
          <span style={{ color: C.muted }}>Your password, then a one-time code sent to your email.</span>
        </Field>
      </dl>
      <div className="mt-5 border-t pt-4" style={{ borderColor: C.line }}>
        <button
          type="button"
          onClick={async () => {
            await signOut();
            router.replace("/sign-in");
          }}
          className={`inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-sm font-semibold transition-colors hover:bg-white/10 sm:min-h-9 ${focusRing}`}
          style={{ ...quietButton, color: C.ink }}
        >
          <SignOut className="size-4" aria-hidden />
          Sign out
        </button>
      </div>
    </Panel>
  );
}

function ChangePassword({ announce }: { announce: Announce }) {
  const { me } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const email = me?.email ?? "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setDone(false);
    if (!current) return setError("Enter your current password.");
    if (!passwordRules(next, email).every((r) => r.ok)) return setError("Choose a new password that meets the rules.");
    if (next !== confirm) return setError("The two new passwords don't match.");
    setError(null);
    setBusy(true);
    try {
      await authApi.changePassword({ current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
      announce("Password changed. Other devices were signed out.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change the password. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Password" lead="Changing it signs out every other device. Forgot it? Sign out and choose “Forgot password”.">
      <form onSubmit={submit} noValidate className="flex max-w-md flex-col gap-4">
        <PasswordField label="Current password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <PasswordField
          label="New password"
          autoComplete="new-password"
          maxLength={128}
          value={next}
          aria-describedby="change-password-rules"
          onChange={(e) => setNext(e.target.value)}
        />
        <PasswordChecklist id="change-password-rules" password={next} email={email} />
        <PasswordField label="Confirm new password" autoComplete="new-password" maxLength={128} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && (
          <p role="alert" className="text-[13.5px]" style={{ color: C.danger }}>
            {error}
          </p>
        )}
        {done && !error && (
          <p role="status" className="flex items-center gap-1.5 text-[13.5px]" style={{ color: C.mint }}>
            <CheckCircle className="size-4" weight="fill" aria-hidden />
            Password changed. Other devices were signed out.
          </p>
        )}
        <div>
          <button type="submit" disabled={busy} className={`rounded-full px-5 py-2.5 text-sm font-semibold disabled:opacity-60 ${focusRing}`} style={primaryButton}>
            {busy ? "Changing…" : "Change password"}
          </button>
        </div>
      </form>
    </Panel>
  );
}

function Devices({ announce }: { announce: Announce }) {
  const q = useSWR("auth-sessions", () => authApi.sessions());
  const [busy, setBusy] = useState<string | null>(null);
  const sessions = q.data?.sessions ?? [];
  const others = sessions.filter((s) => !s.current);

  async function revoke(s: AuthSession) {
    setBusy(s.id);
    try {
      await authApi.revokeSession(s.id);
      announce(`${deviceName(s.user_agent).label} was signed out.`);
      await q.mutate();
    } finally {
      setBusy(null);
    }
  }

  async function revokeOthers() {
    setBusy("others");
    try {
      const { revoked } = await authApi.revokeOtherSessions();
      announce(revoked === 1 ? "One other device was signed out." : `${revoked} other devices were signed out.`);
      await q.mutate();
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel title="Signed-in devices" lead="Where your account is signed in now. A session ends after 14 days, or 3 days unused.">
      {q.error ? (
        <LoadFailure what="your devices" onRetry={() => q.mutate()} />
      ) : !q.data ? (
        <div role="status" className="h-16 rounded-xl motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.03)" }}>
          <span className="sr-only">Loading your devices…</span>
        </div>
      ) : (
        <>
          <ul className="divide-y" style={{ borderColor: C.line }}>
            {sessions.map((s) => {
              const device = deviceName(s.user_agent);
              const Icon = device.mobile ? DeviceMobile : Desktop;
              return (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3" style={{ borderColor: C.line }}>
                  <div className="flex min-w-0 items-start gap-3">
                    <Icon className="mt-0.5 size-5 shrink-0" style={{ color: s.current ? C.mint : C.muted }} aria-hidden />
                    <div className="min-w-0">
                      <p className="text-[14.5px] font-semibold">
                        {device.label}
                        {s.current && (
                          <span className="ml-2 text-[12.5px] font-semibold" style={{ color: C.mint }}>
                            This device
                          </span>
                        )}
                      </p>
                      <p className="text-[12.5px]" style={{ color: C.muted }}>
                        Active <Timestamp at={s.last_seen_at} /> · signed in <Timestamp at={s.created_at} />
                        {s.ip ? <span className="font-mono"> · {s.ip}</span> : null}
                      </p>
                    </div>
                  </div>
                  {!s.current && (
                    <SmallButton onClick={() => revoke(s)} disabled={busy !== null} tone="danger" label={`Sign out ${device.label}`}>
                      {busy === s.id ? "Signing out…" : "Sign out"}
                    </SmallButton>
                  )}
                </li>
              );
            })}
          </ul>
          {others.length > 0 && (
            <div className="mt-3 border-t pt-4" style={{ borderColor: C.line }}>
              <SmallButton onClick={revokeOthers} disabled={busy !== null}>
                {busy === "others" ? "Signing out…" : `Sign out ${others.length === 1 ? "the other device" : `all ${others.length} other devices`}`}
              </SmallButton>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}
