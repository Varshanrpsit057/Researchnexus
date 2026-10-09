"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { AuthProvider } from "@/lib/auth/auth-context";
import { getAuthEpoch, subscribeToAuth } from "@/lib/auth/session";
import { ApiError } from "@/lib/api/client";

export function Providers({ children }: { children: ReactNode }) {
  // One data cache per signed-in session: signing in or out (here or in
  // another tab) starts a fresh cache, so a response fetched for one account
  // can never be shown -- or de-duplicated into -- another's.
  const epoch = useSyncExternalStore(subscribeToAuth, getAuthEpoch, () => 0);
  return (
    <SWRConfig
      key={epoch}
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
