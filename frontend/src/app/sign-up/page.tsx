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
  PasswordChecklist,
  PasswordField,
  passwordRules,
  safeNext,
  SubmitButton,
  takeHandedOffEmail,
  TextLink,
} from "@/components/auth/AuthUi";
import { CodeStep } from "@/components/auth/CodeStep";

export default function SignUpPage() {
  return (
    <Suspense>
      <SignUp />
    </Suspense>
  );
}

function SignUp() {
  const { signUp, verifyCode, resendCode, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [name, setName] = useState("");
  const [email, setEmail] = useState(takeHandedOffEmail);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState<AuthChallenge | null>(null);

  useEffect(() => {
    if (!isLoading && isAuthenticated && !challenge) router.replace(next);
  }, [isLoading, isAuthenticated, challenge, next, router]);

  const nameError = touched && !name.trim() ? "Enter your name." : null;
  const emailError = touched ? emailProblem(email) : null;
  const passwordOk = passwordRules(password, email).every((r) => r.ok);
  const passwordError = touched && !passwordOk ? "Choose a password that meets the rules below." : null;
  const confirmError = touched && confirm !== password ? "The two passwords don't match." : null;

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setTouched(true);
    if (!name.trim() || emailProblem(email) || !passwordOk || confirm !== password) return;
    setError(null);
    setBusy(true);
    try {
      setChallenge(await signUp(name.trim(), email.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (challenge) {
    return (
      <AuthShell title="Confirm your email" lead="Enter the code we sent to finish creating your account.">
        <CodeStep
          challenge={challenge}
          submitLabel="Create account"
          busyLabel="Creating your account…"
          onSubmit={async (code) => {
            await verifyCode(challenge.challenge_id, code);
            router.replace(next);
          }}
          onResend={() => resendCode(challenge.challenge_id)}
          onBack={() => setChallenge(null)}
          backLabel="Change your details"
        />
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Create your account"
      lead="Your papers, workspaces and model keys stay in your account. We'll email a code to confirm the address."
      footer={
        <p>
          Already have an account?{" "}
          <span onClickCapture={() => handOffEmail(email)}>
            <TextLink href={`/sign-in${params.get("next") ? `?next=${encodeURIComponent(next)}` : ""}`}>Sign in</TextLink>
          </span>
        </p>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        <AuthField label="Name" name="name" autoComplete="name" required maxLength={120} value={name} error={nameError} onChange={(e) => setName(e.target.value)} />
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
        <PasswordField
          label="Password"
          name="new-password"
          autoComplete="new-password"
          required
          maxLength={128}
          value={password}
          error={passwordError}
          aria-describedby="password-rules"
          onChange={(e) => setPassword(e.target.value)}
        />
        <PasswordChecklist id="password-rules" password={password} email={email} />
        <PasswordField
          label="Confirm password"
          name="confirm-password"
          autoComplete="new-password"
          required
          maxLength={128}
          value={confirm}
          error={confirmError}
          onChange={(e) => setConfirm(e.target.value)}
        />
        {error && <FormError>{error}</FormError>}
        <SubmitButton busy={busy} busyLabel="Sending your code…">
          Create account
        </SubmitButton>
      </form>
    </AuthShell>
  );
}
