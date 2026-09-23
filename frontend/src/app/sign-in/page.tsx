"use client";

import { Suspense, useId, useState, type FormEvent, type InputHTMLAttributes } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { motion } from "motion/react";
import { useAuth } from "@/lib/auth/auth-context";
import { ApiError } from "@/lib/api/client";

// Same fixed cinematic palette as the landing page -- sign-in is the last
// step of that public, Persuade-mode experience before the visitor crosses
// into the authenticated app, not an Operate-mode screen itself, so it
// keeps that world's atmosphere rather than the app's light/dark-adaptive
// "Index" tokens.
const INK = "#f3f6ff";
const MUTED = "#9aa6c4";
const MUTED_2 = "#6b7796";
const MINT = "#5df0a8";
const MINT_2 = "#2fd38a";
const MINT_INK = "#032018";
const GLASS_2 = "rgba(16,24,48,.65)";
const LINE_STRONG = "rgba(150,175,230,.22)";
const DANGER = "#ff9b9b";

function CinematicField({ label, id, ...props }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <div className="flex flex-col gap-1.5 text-left">
      <label htmlFor={inputId} className="text-sm font-medium" style={{ color: INK }}>
        {label}
      </label>
      <input
        id={inputId}
        className="h-11 rounded-xl px-3.5 text-sm outline-none transition-colors duration-150"
        style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${LINE_STRONG}`, color: INK }}
        onFocus={(e) => (e.currentTarget.style.borderColor = MINT)}
        onBlur={(e) => (e.currentTarget.style.borderColor = LINE_STRONG)}
        {...props}
      />
    </div>
  );
}

export default function SignInPage() {
  return (
    <Suspense>
      <SignInForm />
    </Suspense>
  );
}

function SignInForm() {
  const { signIn } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signIn(email, password);
      router.replace(searchParams.get("next") || "/home");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4" style={{ color: INK }}>
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: "radial-gradient(80% 60% at 50% 40%, rgba(4,6,15,.75) 0%, rgba(4,6,15,.35) 55%, transparent 78%)" }}
      />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.22, 0.7, 0.2, 1] }}
        className="relative z-10 w-full max-w-sm rounded-[22px] px-8 py-9 text-center backdrop-blur-[18px]"
        style={{ background: GLASS_2, border: `1px solid ${LINE_STRONG}`, boxShadow: "0 30px 80px -30px rgba(0,0,0,.75)" }}
      >
        <div className="mb-7 flex flex-col items-center gap-2">
          <span
            className="flex size-10 items-center justify-center rounded-full text-lg font-bold"
            style={{ background: `linear-gradient(180deg, ${MINT}, ${MINT_2})`, color: MINT_INK }}
          >
            ▲
          </span>
          <h1 className="text-lg font-bold tracking-tight">Sign in to ResearchNexus</h1>
          <p className="text-sm" style={{ color: MUTED }}>
            Any email works in this development build. There is no password check yet.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <CinematicField
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <CinematicField
            label="Password"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && (
            <p role="alert" className="flex items-center gap-1.5 text-left text-sm" style={{ color: DANGER }}>
              <WarningCircle className="size-4 shrink-0" weight="bold" aria-hidden />
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="mt-1 inline-flex h-11 items-center justify-center rounded-xl text-sm font-semibold transition-transform duration-150 active:scale-[0.98] disabled:opacity-60"
            style={{
              color: MINT_INK,
              background: `linear-gradient(180deg, ${MINT}, ${MINT_2})`,
              boxShadow: "0 10px 30px -8px rgba(93,240,168,.55)",
            }}
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-5 text-center text-xs" style={{ color: MUTED_2 }}>
          <Link href="/" className="transition-colors hover:text-white">
            Back to overview
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
