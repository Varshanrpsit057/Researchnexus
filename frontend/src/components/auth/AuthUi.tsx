"use client";

import { useId, useState, type InputHTMLAttributes, type ReactNode, type Ref } from "react";
import Link from "next/link";
import { motion } from "motion/react";
import { CheckCircle, Circle, Eye, EyeSlash, FlaskIcon, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import BlurText from "@/components/reactbits/BlurText";
import { CINEMATIC as C } from "@/lib/cinematic-theme";

/* The public, Persuade-mode end of the app -- sign in, sign up, reset a
 * password -- in the same glass card on the navy ground as before, over the
 * one global background. */

export const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5df0a8]";

/** Where to go after signing in: only a path on this site (never another
 * site -- `?next=https://...` must not turn sign-in into a redirect). */
export function safeNext(next: string | null | undefined, fallback = "/home"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  return next;
}

export function AuthShell({ title, lead, children, footer }: { title: string; lead?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-10" style={{ color: C.ink }}>
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: "radial-gradient(80% 60% at 50% 40%, rgba(4,6,15,.75) 0%, rgba(4,6,15,.35) 55%, transparent 78%)" }}
      />
      <motion.main
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.22, 0.7, 0.2, 1] }}
        className="relative z-10 w-full max-w-[400px] rounded-[22px] px-6 py-8 backdrop-blur-[18px] sm:px-8 sm:py-9"
        style={{ background: C.glass2, border: `1px solid ${C.lineStrong}`, boxShadow: "0 30px 80px -30px rgba(0,0,0,.75)" }}
      >
        <div className="mb-7 flex flex-col items-center gap-2 text-center">
          <Link href="/" aria-label="ResearchNexus, overview" className={`rounded-full ${FOCUS}`}>
            <span
              className="flex size-10 items-center justify-center rounded-full"
              style={{ background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})`, color: C.mintInk }}
            >
              <FlaskIcon className="size-5" weight="duotone" aria-hidden />
            </span>
          </Link>
          <BlurText as="h1" text={title} className="text-lg font-bold tracking-tight [text-wrap:balance]" />
          {lead && (
            <p className="text-sm leading-relaxed [text-wrap:pretty]" style={{ color: C.muted }}>
              {lead}
            </p>
          )}
        </div>
        {children}
        {footer && (
          <div className="mt-6 space-y-2 text-center text-[13px]" style={{ color: C.muted }}>
            {footer}
          </div>
        )}
      </motion.main>
    </div>
  );
}

export function TextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className={`rounded-sm font-semibold underline-offset-4 transition-colors hover:underline ${FOCUS}`} style={{ color: C.mint }}>
      {children}
    </Link>
  );
}

const fieldStyle = { background: "rgba(255,255,255,.04)", color: C.ink };

type FieldProps = {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  inputRef?: Ref<HTMLInputElement>;
  trailing?: ReactNode;
} & InputHTMLAttributes<HTMLInputElement>;

export function AuthField({ label, id, hint, error, inputRef, trailing, className = "", onFocus, onBlur, "aria-describedby": describedBy, ...props }: FieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const [focused, setFocused] = useState(false);
  const described = [hint && !error ? hintId : null, error ? errorId : null, describedBy].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5 text-left">
      <label htmlFor={inputId} className="text-sm font-medium" style={{ color: C.ink }}>
        {label}
      </label>
      <div className="relative">
        <input
          id={inputId}
          ref={inputRef}
          aria-describedby={described}
          aria-invalid={error ? true : undefined}
          className={`h-11 w-full rounded-xl px-3.5 text-sm outline-none transition-colors duration-150 ${trailing ? "pr-12" : ""} ${className}`}
          style={{ ...fieldStyle, border: `1px solid ${error ? C.danger : focused ? C.mint : C.lineStrong}` }}
          {...props}
          onFocus={(e) => {
            setFocused(true);
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            onBlur?.(e);
          }}
        />
        {trailing && <div className="absolute inset-y-0 right-1 flex items-center">{trailing}</div>}
      </div>
      {hint && !error && (
        <p id={hintId} className="text-[12.5px] leading-snug" style={{ color: C.muted }}>
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="flex items-start gap-1.5 text-[12.5px] leading-snug" style={{ color: C.danger }}>
          <WarningCircle className="mt-px size-3.5 shrink-0" weight="bold" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}

/** A password field with a show/hide toggle. */
export function PasswordField(props: Omit<FieldProps, "type" | "trailing">) {
  const [visible, setVisible] = useState(false);
  return (
    <AuthField
      {...props}
      type={visible ? "text" : "password"}
      spellCheck={false}
      autoCapitalize="none"
      trailing={
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? `Hide ${props.label.toLowerCase()}` : `Show ${props.label.toLowerCase()}`}
          aria-pressed={visible}
          className={`grid size-9 place-items-center rounded-lg transition-colors hover:bg-white/[0.08] ${FOCUS}`}
          style={{ color: C.muted }}
        >
          {visible ? <EyeSlash className="size-[18px]" aria-hidden /> : <Eye className="size-[18px]" aria-hidden />}
        </button>
      }
    />
  );
}

export const PASSWORD_MIN = 10;

/** The rules the server applies, as the reader types (the server also
 * refuses the most common passwords, and says so). */
export function passwordRules(password: string, email: string) {
  const local = email.split("@")[0]?.toLowerCase() ?? "";
  return [
    { id: "length", label: `At least ${PASSWORD_MIN} characters`, ok: password.length >= PASSWORD_MIN },
    { id: "mix", label: "A letter and a number or symbol", ok: /[A-Za-z]/.test(password) && /[^A-Za-z]/.test(password) },
    { id: "email", label: "Not your email address", ok: password.length > 0 && !(local.length >= 4 && password.toLowerCase().includes(local)) },
  ];
}

export function PasswordChecklist({ password, email, id }: { password: string; email: string; id?: string }) {
  return (
    <ul id={id} className="-mt-1 space-y-1 text-left text-[12.5px]" aria-label="Password rules">
      {passwordRules(password, email).map((rule) => (
        <li key={rule.id} className="flex items-center gap-1.5" style={{ color: rule.ok ? C.ink : C.muted }}>
          {rule.ok ? (
            <CheckCircle className="size-3.5 shrink-0" weight="fill" style={{ color: C.mint }} aria-hidden />
          ) : (
            <Circle className="size-3.5 shrink-0" aria-hidden />
          )}
          {rule.label}
          <span className="sr-only">{rule.ok ? " (met)" : " (not yet)"}</span>
        </li>
      ))}
    </ul>
  );
}

export function FormError({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-1.5 text-left text-sm leading-snug" style={{ color: C.danger }}>
      <WarningCircle className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

export function SubmitButton({ busy, busyLabel, children, disabled }: { busy: boolean; busyLabel: string; children: ReactNode; disabled?: boolean }) {
  return (
    <button
      type="submit"
      disabled={busy || disabled}
      aria-busy={busy || undefined}
      className={`mt-1 inline-flex h-11 items-center justify-center gap-2 rounded-xl text-sm font-semibold transition-transform duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 ${FOCUS}`}
      style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})`, boxShadow: "0 10px 30px -8px rgba(93,240,168,.55)" }}
    >
      {busy && <span className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden />}
      {busy ? busyLabel : children}
    </button>
  );
}

const EMAIL_HANDOFF = "researchnexus.auth-email";

/** The email typed on one auth page, for the next one to start with (kept
 * for this tab only, and never put in a URL). */
export function handOffEmail(email: string): void {
  try {
    if (email.trim()) window.sessionStorage.setItem(EMAIL_HANDOFF, email.trim());
  } catch {
    // storage unavailable: the next page starts empty
  }
}

export function takeHandedOffEmail(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(EMAIL_HANDOFF) ?? "";
  } catch {
    return "";
  }
}

const EMAIL = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/;

export function emailProblem(email: string): string | null {
  if (!email.trim()) return "Enter your email address.";
  if (!EMAIL.test(email.trim())) return "Enter a valid email address, like name@university.edu.";
  return null;
}
