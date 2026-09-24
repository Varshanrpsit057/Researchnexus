"use client";

import { useSyncExternalStore } from "react";

/** A small, honest convenience: the papers this browser has uploaded or
 * opened, so the upload screen has something useful to show without a
 * backend "list papers" endpoint (none exists -- see PRODUCT.md: no fake
 * research results). This is real data about the user's own actions, kept
 * client-side only. */

export interface RecentPaper {
  paperId: string;
  title: string;
  addedAt: string;
}

const KEY = "researchnexus.recent-papers";
const MAX = 8;
const EMPTY: RecentPaper[] = [];

// useSyncExternalStore requires a snapshot that is reference-stable when the
// underlying value hasn't changed (it re-renders whenever the reference
// changes) -- JSON.parse-ing on every call would return a new array every
// time and loop forever, so the parsed result is cached against the raw
// string it came from.
let cachedRaw: string | null = null;
let cachedSnapshot: RecentPaper[] = EMPTY;

function getSnapshot(): RecentPaper[] {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    raw = null;
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedSnapshot = raw ? (JSON.parse(raw) as RecentPaper[]) : EMPTY;
    } catch {
      cachedSnapshot = EMPTY;
    }
  }
  return cachedSnapshot;
}

function getServerSnapshot(): RecentPaper[] {
  return EMPTY;
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("researchnexus:recent-papers", callback);
  return () => window.removeEventListener("researchnexus:recent-papers", callback);
}

export function recordRecentPaper(entry: RecentPaper): void {
  if (typeof window === "undefined") return;
  const existing = getSnapshot().filter((p) => p.paperId !== entry.paperId);
  const next = [entry, ...existing].slice(0, MAX);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    return; // storage blocked or full (e.g. private mode): the history is only a convenience
  }
  window.dispatchEvent(new Event("researchnexus:recent-papers"));
}

export function useRecentPapers(): RecentPaper[] {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
