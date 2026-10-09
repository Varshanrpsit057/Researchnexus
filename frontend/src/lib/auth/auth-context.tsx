"use client";

import { createContext, useCallback, useContext, useEffect, type ReactNode } from "react";
import useSWR from "swr";
import { auth } from "@/lib/api/endpoints";
import type { AuthChallenge, MeResponse } from "@/lib/api/types";
import { forgetLegacyToken, notifyAuthChanged, subscribeToUnauthorized } from "./session";

interface AuthContextValue {
  isAuthenticated: boolean;
  /** true until the server has said who (if anyone) is signed in */
  isLoading: boolean;
  me: MeResponse | undefined;
  /** step 1 of sign-up: a code goes to the email */
  signUp: (name: string, email: string, password: string) => Promise<AuthChallenge>;
  /** step 1 of sign-in: the password checks out, a code goes to the email */
  logIn: (email: string, password: string) => Promise<AuthChallenge>;
  /** step 2 of either: the emailed code makes the session */
  verifyCode: (challengeId: string, code: string) => Promise<MeResponse>;
  resendCode: (challengeId: string) => Promise<AuthChallenge>;
  requestPasswordReset: (email: string) => Promise<AuthChallenge>;
  resetPassword: (challengeId: string, code: string, password: string) => Promise<MeResponse>;
  signOut: () => Promise<void>;
  refreshMe: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Who is signed in: asked of the server (the session is an httpOnly cookie
 * scripts can't read). `null` = nobody; `undefined` = not known yet. */
async function whoAmI(): Promise<MeResponse | null> {
  return (await auth.session()).user;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data: me, error, mutate } = useSWR("me", whoAmI, {
    shouldRetryOnError: false,
    revalidateOnFocus: true,
    focusThrottleInterval: 60_000,
  });

  useEffect(() => {
    forgetLegacyToken();
    // a request found the session ended: check again (and the page guards redirect)
    return subscribeToUnauthorized(() => void mutate());
  }, [mutate]);

  // every sign-in and sign-out gets a fresh data cache (Providers keys it by
  // the auth epoch), so no other account's responses can show
  const signedIn = useCallback((user: MeResponse) => {
    notifyAuthChanged();
    return user;
  }, []);

  const value: AuthContextValue = {
    isAuthenticated: Boolean(me),
    isLoading: me === undefined && !error,
    me: me ?? undefined,
    signUp: (name, email, password) => auth.signUp({ name, email, password }),
    logIn: (email, password) => auth.logIn({ email, password }),
    verifyCode: async (challengeId, code) => signedIn((await auth.verify({ challenge_id: challengeId, code })).user),
    resendCode: (challengeId) => auth.resend(challengeId),
    requestPasswordReset: (email) => auth.forgotPassword(email),
    resetPassword: async (challengeId, code, password) =>
      signedIn((await auth.resetPassword({ challenge_id: challengeId, code, password })).user),
    signOut: async () => {
      try {
        await auth.logout();
      } finally {
        notifyAuthChanged();
      }
    },
    refreshMe: () => void mutate(),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
