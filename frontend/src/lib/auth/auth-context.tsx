"use client";

import { createContext, useCallback, useContext, useSyncExternalStore, type ReactNode } from "react";
import useSWR from "swr";
import { auth } from "@/lib/api/endpoints";
import { clearToken, getToken, setToken } from "./token";
import type { MeResponse } from "@/lib/api/types";

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  me: MeResponse | undefined;
  signIn: (email: string, password: string) => Promise<void>;
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
 * render on every fresh navigation, and AppShell would read that render as
 * "not authenticated" and redirect to /sign-in before the real client value
 * (which may well be "yes, there is a token") ever gets a chance to apply. */
type TokenState = "unknown" | "present" | "absent";

function subscribeToToken(callback: () => void): () => void {
  window.addEventListener("researchnexus:auth", callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener("researchnexus:auth", callback);
    window.removeEventListener("storage", callback);
  };
}

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

  const signIn = useCallback(async (email: string, password: string) => {
    const session = await auth.createSession(email, password);
    setToken(session.token);
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
