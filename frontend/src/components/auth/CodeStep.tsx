"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ArrowLeft, EnvelopeSimple } from "@phosphor-icons/react/dist/ssr";
import DecryptedText from "@/components/reactbits/DecryptedText";
import { ApiError } from "@/lib/api/client";
import type { AuthChallenge } from "@/lib/api/types";
import { CINEMATIC as C } from "@/lib/cinematic-theme";
import { AuthField, FOCUS, FormError, SubmitButton } from "./AuthUi";

/** Seconds left until `deadline` (a ms timestamp), ticking every second. */
function useCountdown(deadline: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [deadline]);
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

// a code that can't be used again: the only way on is to start over
const DEAD_END = new Set(["code_used", "code_locked", "code_invalid", "resend_limit", "email_taken"]);

interface CodeStepProps {
  challenge: AuthChallenge;
  /** what entering the code finishes ("Sign in", "Create account", "Reset password") */
  submitLabel: string;
  busyLabel: string;
  /** extra fields shown with the code (a new password, when resetting) */
  children?: ReactNode;
  /** checked before sending; a message stops the submit */
  validate?: () => string | null;
  onSubmit: (code: string) => Promise<void>;
  onResend: () => Promise<AuthChallenge>;
  onBack: () => void;
  backLabel: string;
}

/** The second step of every way in: enter the six-digit code we emailed. */
export function CodeStep({ challenge, submitLabel, busyLabel, children, validate, onSubmit, onResend, onBack, backLabel }: CodeStepProps) {
  const [current, setCurrent] = useState(challenge);
  const [issuedAt, setIssuedAt] = useState(() => Date.now());
  const expiresLeft = useCountdown(issuedAt + current.expires_in * 1000);
  const resendLeft = useCountdown(issuedAt + current.resend_in * 1000);
  const [code, setCode] = useState("");
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const expired = expiresLeft === 0;

  useEffect(() => inputRef.current?.focus(), []);

  async function submit(value: string) {
    const problem = validate?.() ?? null;
    if (value.length !== 6) {
      setError({ code: "incomplete", message: "Enter all six digits of the code." });
      return;
    }
    if (problem) {
      setError({ code: "invalid", message: problem });
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await onSubmit(value);
    } catch (err) {
      setError(err instanceof ApiError ? { code: err.code, message: err.message } : { code: "network", message: "Couldn't reach the server. Check your connection and try again." });
      setCode("");
      inputRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    setNotice(null);
    setResending(true);
    try {
      const next = await onResend();
      setCurrent(next);
      setIssuedAt(Date.now());
      setCode("");
      setNotice("A new code is on its way. The earlier one no longer works.");
      inputRef.current?.focus();
    } catch (err) {
      setError(err instanceof ApiError ? { code: err.code, message: err.message } : { code: "network", message: "Couldn't send a new code. Try again." });
    } finally {
      setResending(false);
    }
  }

  const deadEnd = error !== null && DEAD_END.has(error.code);
  const canResend = !deadEnd && resendLeft === 0 && current.resends_left > 0 && !resending;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start gap-3 rounded-xl px-3.5 py-3 text-left text-[13.5px] leading-relaxed" style={{ background: "rgba(93,240,168,.06)", border: "1px solid rgba(93,240,168,.22)" }}>
        <EnvelopeSimple className="mt-0.5 size-[18px] shrink-0" style={{ color: C.mint }} aria-hidden />
        <p>
          We sent a 6-digit code to{" "}
          <DecryptedText text={current.destination} className="font-semibold" encryptedClassName="font-semibold opacity-50" />.{" "}
          <span style={{ color: C.muted }}>Check your spam folder if it isn&apos;t in your inbox.</span>
        </p>
      </div>

      <form
        ref={formRef}
        noValidate
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void submit(code);
        }}
        className="flex flex-col gap-4"
      >
        <AuthField
          label="Code"
          inputRef={inputRef}
          name="one-time-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          maxLength={6}
          placeholder="••••••"
          value={code}
          disabled={busy || deadEnd}
          error={error && !deadEnd && error.code !== "invalid" ? error.message : null}
          hint={expired ? "This code has expired. Send a new one." : `The code expires in ${clock(expiresLeft)}.`}
          className="text-center font-mono text-[22px] tracking-[0.5em] placeholder:tracking-[0.5em]"
          onChange={(e) => {
            const digits = e.target.value.replace(/\D/g, "").slice(0, 6);
            setCode(digits);
            if (error?.code === "incomplete" || error?.code === "code_wrong") setError(null);
            // all six typed or pasted, and nothing else to fill in: go
            if (digits.length === 6 && !children && !busy) void submit(digits);
          }}
        />
        {children}
        {error && error.code === "invalid" && <FormError>{error.message}</FormError>}
        {deadEnd && error && <FormError>{error.message}</FormError>}
        {notice && !error && (
          <p role="status" className="text-left text-[13px]" style={{ color: C.mint }}>
            {notice}
          </p>
        )}
        {!deadEnd && (
          <SubmitButton busy={busy} busyLabel={busyLabel} disabled={expired}>
            {submitLabel}
          </SubmitButton>
        )}
      </form>

      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
        <button type="button" onClick={onBack} className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 transition-colors hover:text-white ${FOCUS}`} style={{ color: C.muted }}>
          <ArrowLeft className="size-3.5" aria-hidden />
          {backLabel}
        </button>
        {!deadEnd && (
          <button
            type="button"
            onClick={() => void resend()}
            disabled={!canResend}
            className={`rounded-full px-2 py-1 font-semibold transition-colors enabled:hover:underline disabled:cursor-not-allowed ${FOCUS}`}
            style={{ color: canResend ? C.mint : C.muted2 }}
          >
            {resending
              ? "Sending…"
              : current.resends_left === 0
                ? "No more codes for this attempt"
                : resendLeft > 0
                  ? `Send a new code in ${resendLeft} s`
                  : "Send a new code"}
          </button>
        )}
      </div>
    </div>
  );
}
