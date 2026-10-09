"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/auth-context";
import { ApiError } from "@/lib/api/client";
import type { AuthChallenge } from "@/lib/api/types";
import {
  AuthField,
  AuthShell,
  emailProblem,
  FormError,
  handOffEmail,
  PasswordField,
  safeNext,
  SubmitButton,
  takeHandedOffEmail,
  TextLink,
} from "@/components/auth/AuthUi";
import { CodeStep } from "@/components/auth/CodeStep";

export default function SignInPage() {
  return (
    <Suspense>
      <SignIn />
    </Suspense>
  );
}

function SignIn() {
  const { logIn, verifyCode, resendCode, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState(takeHandedOffEmail);
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState<AuthChallenge | null>(null);

  // already signed in (another tab, or back to this page): straight on
  useEffect(() => {
    if (!isLoading && isAuthenticated && !challenge) router.replace(next);
  }, [isLoading, isAuthenticated, challenge, next, router]);

  const emailError = touched ? emailProblem(email) : null;
  const passwordError = touched && !password ? "Enter your password." : null;

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setTouched(true);
    if (emailProblem(email) || !password) return;
    setError(null);
    setBusy(true);
    try {
      setChallenge(await logIn(email.trim(), password));
      setPassword("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (challenge) {
    return (
      <AuthShell title="Check your email" lead="One more step: enter the code we just sent, so we know it's really you.">
        <CodeStep
          challenge={challenge}
          submitLabel="Sign in"
          busyLabel="Signing in…"
          onSubmit={async (code) => {
            await verifyCode(challenge.challenge_id, code);
            router.replace(next);
          }}
          onResend={() => resendCode(challenge.challenge_id)}
          onBack={() => setChallenge(null)}
          backLabel="Use a different email"
        />
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Sign in to ResearchNexus"
      lead="Welcome back. After your password, we'll email you a one-time code."
      footer={
        <p>
          New here? <TextLink href={`/sign-up${params.get("next") ? `?next=${encodeURIComponent(next)}` : ""}`}>Create an account</TextLink>
        </p>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        <AuthField
          label="Email"
          type="email"
          name="email"
          autoComplete="email username"
          inputMode="email"
          required
          value={email}
          error={emailError}
          onChange={(e) => setEmail(e.target.value)}
        />
        <div className="flex flex-col gap-1.5">
          <PasswordField
            label="Password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            error={passwordError}
            onChange={(e) => setPassword(e.target.value)}
          />
          <div className="text-right text-[12.5px]" onClickCapture={() => handOffEmail(email)}>
            <TextLink href="/forgot-password">Forgot password?</TextLink>
          </div>
        </div>
        {error && <FormError>{error}</FormError>}
        <SubmitButton busy={busy} busyLabel="Checking…">
          Continue
        </SubmitButton>
      </form>
    </AuthShell>
  );
}
