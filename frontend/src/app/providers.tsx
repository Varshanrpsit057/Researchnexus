"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { AuthProvider } from "@/lib/auth/auth-context";
import { getToken, subscribeToToken } from "@/lib/auth/token";
import { ApiError } from "@/lib/api/client";

export function Providers({ children }: { children: ReactNode }) {
  // One data cache per signed-in session: a new token (sign-in, sign-out, or
  // either in another tab) starts a fresh cache, so a response fetched for
  // one account can never be shown -- or de-duplicated into -- another's.
  const token = useSyncExternalStore(subscribeToToken, getToken, () => null);
  return (
    <SWRConfig
      key={token ?? "signed-out"}
      value={{
        provider: () => new Map(),
        shouldRetryOnError: (err) => !(err instanceof ApiError && err.status < 500),
        revalidateOnFocus: false,
      }}
    >
      <AuthProvider>{children}</AuthProvider>
    </SWRConfig>
  );
}
