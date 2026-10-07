"use client";

import { useSyncExternalStore } from "react";

/**
 * The publishers the reader prefers (remediation, 2026-10-06): chosen in
 * Settings, kept in this browser like the ranking weights, and sent with
 * every discovery and re-ranking so the "Preferred publisher" criterion and
 * the results' publisher filter use them. The default is the four the reader
 * first asked for.
 */

export const DEFAULT_PUBLISHERS: readonly string[] = ["IEEE", "Springer", "ACM", "Elsevier"];

/** "IEEE, Springer, ACM or Elsevier"; "no publisher" when none is chosen. */
export function publishersPhrase(list: readonly string[]): string {
  if (list.length === 0) return "no publisher";
  if (list.length === 1) return list[0];
  return `${list.slice(0, -1).join(", ")} or ${list[list.length - 1]}`;
}

export function samePublishers(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((p, i) => p === b[i]);
}

/** Whether a paper's publisher is one the reader prefers. */
export function isPreferred(publisher: string | null | undefined, preferred: readonly string[]): boolean {
  return publisher != null && preferred.includes(publisher);
}

const KEY = "researchnexus.pref.preferredPublishers";
const EVENT = "researchnexus:preferred-publishers";

export function readPublishers(): readonly string[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return DEFAULT_PUBLISHERS;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed) || !parsed.every((p) => typeof p === "string")) return DEFAULT_PUBLISHERS;
    return parsed.slice(0, 30);
  } catch {
    return DEFAULT_PUBLISHERS; // unreadable or storage blocked: the defaults, quietly
  }
}

export function writePublishers(list: readonly string[]): boolean {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(EVENT));
  return true;
}

let cached: { raw: string | null; value: readonly string[] } | null = null;

function snapshot(): readonly string[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    raw = null;
  }
  if (!cached || cached.raw !== raw) cached = { raw, value: readPublishers() };
  return cached.value;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The publishers this browser prefers (the default four until changed). */
export function useSavedPublishers(): readonly string[] {
  return useSyncExternalStore(subscribe, snapshot, () => DEFAULT_PUBLISHERS);
}
