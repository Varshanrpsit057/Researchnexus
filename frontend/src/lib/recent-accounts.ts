"use client";

import { useSyncExternalStore } from "react";

/**
 * The accounts this browser has signed in to (remediation, 2026-10-06).
 * Sign-in accepts any email and makes a new, empty account for one it hasn't
 * seen, so a typo or a different address "loses" a reader's work. The
 * sign-in page offers these and says when an email is new here. Emails only,
 * kept in this browser.
 */

export interface RecentAccount {
  email: string;
  lastUsedAt: string;
}

const KEY = "researchnexus.recent-accounts";
const EVENT = "researchnexus:recent-accounts";
const MAX = 5;
const EMPTY: RecentAccount[] = [];

export const normalizeEmail = (email: string): string => email.trim().toLowerCase();

/** The list with `email` first (once, any case), newest first, at most five. */
export function withAccount(list: RecentAccount[], email: string, at: string): RecentAccount[] {
  const key = normalizeEmail(email);
  if (!key) return list;
  return [{ email: key, lastUsedAt: at }, ...list.filter((a) => normalizeEmail(a.email) !== key)].slice(0, MAX);
}

export function isKnownAccount(list: RecentAccount[], email: string): boolean {
  const key = normalizeEmail(email);
  return list.some((a) => normalizeEmail(a.email) === key);
}

let cachedRaw: string | null = null;
let cached: RecentAccount[] = EMPTY;

function read(): RecentAccount[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    raw = null;
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      cached = Array.isArray(parsed)
        ? parsed.filter((a): a is RecentAccount => typeof a?.email === "string" && typeof a?.lastUsedAt === "string").slice(0, MAX)
        : EMPTY;
    } catch {
      cached = EMPTY;
    }
  }
  return cached;
}

function write(list: RecentAccount[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    return; // storage blocked: nothing remembered, nothing breaks
  }
  window.dispatchEvent(new CustomEvent(EVENT));
}

export function recordAccount(email: string): void {
  write(withAccount(read(), email, new Date().toISOString()));
}

export function forgetAccount(email: string): void {
  const key = normalizeEmail(email);
  write(read().filter((a) => normalizeEmail(a.email) !== key));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function useRecentAccounts(): RecentAccount[] {
  return useSyncExternalStore(subscribe, read, () => EMPTY);
}

// a sign-in that made a new account, said once on the next page
const NEW_KEY = "researchnexus.new-account";

export function noteNewAccount(email: string): void {
  try {
    window.sessionStorage.setItem(NEW_KEY, normalizeEmail(email));
  } catch {
    // storage blocked: the notice is skipped
  }
}

/** The email of an account the last sign-in just made; null otherwise. A
 * pure read (safe in render); `clearNewAccount` makes it a one-time notice. */
export function peekNewAccount(): string | null {
  try {
    return window.sessionStorage.getItem(NEW_KEY);
  } catch {
    return null; // no window (server render) or storage blocked
  }
}

export function clearNewAccount(): void {
  try {
    window.sessionStorage.removeItem(NEW_KEY);
  } catch {
    // nothing to clear
  }
}
