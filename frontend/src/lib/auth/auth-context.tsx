"use client";

import { createContext, useCallback, useContext, useSyncExternalStore, type ReactNode } from "react";
import useSWR from "swr";
import { auth } from "@/lib/api/endpoints";
import { clearToken, getToken, setToken, subscribeToToken } from "./token";
import { noteNewAccount, recordAccount } from "@/lib/recent-accounts";
import type { MeResponse } from "@/lib/api/types";

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  me: MeResponse | undefined;
  /** resolves whether the server made a new, empty account for this email */
  signIn: (email: string, password: string) => Promise<{ created: boolean }>;
  signOut: () => void;
  refreshMe: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** The token lives in localStorage, a store outside React --
 * useSyncExternalStore keeps `hasToken` in sync with it (including cross-tab
 * `storage` events) without a useState+useEffect mount-sync, and without
 * ever touching localStorage during SSR (`getServerSnapshot` below).
 *
 * The snapshot is deliberately three-valued, not a plain boolean: the
 * server/first-hydration-pass value must be distinguishable from a
 * confirmed "no token", or `isLoading` below would read false for one
 * render on every fresh navigation, and a page would read that render as
 * "not authenticated" and redirect to /sign-in before the real client value
 * (which may well be "yes, there is a token") ever gets a chance to apply. */
type TokenState = "unknown" | "present" | "absent";

function getTokenSnapshot(): TokenState {
  return getToken() ? "present" : "absent";
}

function getTokenServerSnapshot(): TokenState {
  return "unknown";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const tokenState = useSyncExternalStore(subscribeToToken, getTokenSnapshot, getTokenServerSnapshot);
  const hasToken = tokenState === "present";

  const { data: me, isLoading: meLoading, mutate } = useSWR(hasToken ? "me" : null, () => auth.me(), {
    shouldRetryOnError: false,
    revalidateOnFocus: false,
  });

  // every sign-in and sign-out gets a fresh data cache (Providers keys it by
  // the token), so no other account's responses can show
  const signIn = useCallback(async (email: string, password: string) => {
    const session = await auth.createSession(email, password);
    recordAccount(email);
    if (session.created) noteNewAccount(email);
    setToken(session.token);
    return { created: Boolean(session.created) };
  }, []);

  const signOut = useCallback(() => {
    clearToken();
  }, []);

  const value: AuthContextValue = {
    isAuthenticated: Boolean(hasToken && me),
    isLoading: tokenState === "unknown" || (hasToken && meLoading),
    me,
    signIn,
    signOut,
    refreshMe: () => mutate(),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
