"use client";

import { Suspense, useState, type FormEvent } from "react";
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
  PasswordChecklist,
  PasswordField,
  passwordRules,
  safeNext,
  SubmitButton,
  takeHandedOffEmail,
  TextLink,
} from "@/components/auth/AuthUi";
import { CodeStep } from "@/components/auth/CodeStep";

export default function ForgotPasswordPage() {
  return (
    <Suspense>
      <ForgotPassword />
    </Suspense>
  );
}

function ForgotPassword() {
  const { requestPasswordReset, resetPassword, resendCode } = useAuth();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [email, setEmail] = useState(takeHandedOffEmail);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState<AuthChallenge | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  const emailError = touched ? emailProblem(email) : null;

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setTouched(true);
    if (emailProblem(email)) return;
    setError(null);
    setBusy(true);
    try {
      setChallenge(await requestPasswordReset(email.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (challenge) {
    return (
      <AuthShell
        title="Choose a new password"
        lead="If an account uses this email, a code is on its way. Enter it with your new password; every other device will be signed out."
      >
        <CodeStep
          challenge={challenge}
          submitLabel="Reset password and sign in"
          busyLabel="Saving…"
          validate={() => {
            if (!passwordRules(password, email).every((r) => r.ok)) return "Choose a password that meets the rules.";
            if (confirm !== password) return "The two passwords don't match.";
            return null;
          }}
          onSubmit={async (code) => {
            await resetPassword(challenge.challenge_id, code, password);
            router.replace(next);
          }}
          onResend={() => resendCode(challenge.challenge_id)}
          onBack={() => setChallenge(null)}
          backLabel="Use a different email"
        >
          <PasswordField
            label="New password"
            name="new-password"
            autoComplete="new-password"
            required
            maxLength={128}
            value={password}
            aria-describedby="new-password-rules"
            onChange={(e) => setPassword(e.target.value)}
          />
          <PasswordChecklist id="new-password-rules" password={password} email={email} />
          <PasswordField
            label="Confirm new password"
            name="confirm-password"
            autoComplete="new-password"
            required
            maxLength={128}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </CodeStep>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      lead="Enter your account's email and we'll send a code to set a new password. Accounts made before ResearchNexus had passwords get theirs this way too."
      footer={
        <p>
          Remembered it?{" "}
          <span onClickCapture={() => handOffEmail(email)}>
            <TextLink href="/sign-in">Back to sign in</TextLink>
          </span>
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
        {error && <FormError>{error}</FormError>}
        <SubmitButton busy={busy} busyLabel="Sending…">
          Send a code
        </SubmitButton>
      </form>
    </AuthShell>
  );
}
