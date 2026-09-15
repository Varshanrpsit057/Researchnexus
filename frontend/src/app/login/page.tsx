"use client";

import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { FlaskIcon } from "@phosphor-icons/react/dist/ssr";
import { useAuth } from "@/lib/auth/auth-context";
import { TextInput } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/States";
import { ApiError } from "@/lib/api/client";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
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
      router.replace(searchParams.get("next") || "/papers");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-surface-sunken px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2 text-center">
          <FlaskIcon className="size-8 text-accent" weight="duotone" aria-hidden />
          <h1 className="text-lg font-semibold tracking-tightest text-ink">Sign in to ResearchNexus</h1>
          <p className="text-sm text-ink-muted">
            Any email works in this development build. There is no password check yet.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 border border-border bg-surface-raised p-6">
          <TextInput
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <TextInput
            label="Password"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <InlineError message={error} />}
          <Button type="submit" loading={submitting} className="mt-1">
            Sign in
          </Button>
        </form>
        <p className="mt-4 text-center text-xs text-ink-subtle">
          <Link href="/" className="hover:text-ink-muted">
            Back to overview
          </Link>
        </p>
      </div>
    </div>
  );
}
