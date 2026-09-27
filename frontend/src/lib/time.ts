"use client";

import { useSyncExternalStore } from "react";

/**
 * Every time on screen, read and written one way (remediation Phase 4).
 *
 * The backend keeps and sends every timestamp in UTC. It is turned into the
 * reader's own time here and nowhere else -- one parser, one set of
 * formatters, one clock -- so a page can't read a zone-less timestamp as
 * local time (hours off, sometimes the wrong day), or say "1 min ago" for
 * something 30 seconds old, or "yesterday" for something two days back.
 */

const ZONED = /(?:[zZ]|[+-]\d\d:?\d\d)$/;
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** A backend timestamp as the instant it names. One without a zone (older
 * rows, SQLite text) is UTC, never the browser's local time. */
export function parseTimestamp(iso: string): Date {
  const text = iso.trim().replace(" ", "T");
  return new Date(ZONED.test(text) ? text : `${text}Z`);
}

function valid(date: Date): boolean {
  return !Number.isNaN(date.getTime());
}

/** Whole calendar days between two instants, in the reader's own timezone. */
function calendarDaysBetween(earlier: Date, later: Date): number {
  const day = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY;
  return Math.round(day(later) - day(earlier));
}

/**
 * "just now", "5 min ago", "3 h ago", "yesterday", "4 days ago", then a date.
 * Counts down, never up (30 s is "just now", 90 min is "1 h ago"); a moment
 * in the future -- a clock a little ahead -- is "just now" too.
 */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = parseTimestamp(iso);
  if (!valid(then)) return "";
  const ago = now - then.getTime();
  if (ago < MINUTE) return "just now";
  if (ago < HOUR) return `${Math.floor(ago / MINUTE)} min ago`;
  if (ago < DAY) return `${Math.floor(ago / HOUR)} h ago`;
  const days = calendarDaysBetween(then, new Date(now));
  if (days <= 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return formatDate(iso, { now });
}

interface FormatOptions {
  /** The reader's timezone and language unless given (tests pin them). */
  timeZone?: string;
  locale?: string;
  now?: number;
}

/** "Sep 3", or "Sep 3, 2025" outside the current year. */
export function formatDate(iso: string, { timeZone, locale, now = Date.now() }: FormatOptions = {}): string {
  const date = parseTimestamp(iso);
  if (!valid(date)) return "";
  const year = (d: Date) => new Intl.DateTimeFormat("en-US", { year: "numeric", timeZone }).format(d);
  const sameYear = year(date) === year(new Date(now));
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }), timeZone }).format(date);
}

/** "27 September 2026": a day on its own, spelled out. */
export function formatLongDate(iso: string, { timeZone, locale }: FormatOptions = {}): string {
  const date = parseTimestamp(iso);
  return valid(date) ? new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric", timeZone }).format(date) : "";
}

/** "Sep 27, 2026, 4:21 PM": the exact moment, in the reader's time. */
export function formatDateTime(iso: string, { timeZone, locale }: FormatOptions = {}): string {
  const date = parseTimestamp(iso);
  return valid(date) ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone }).format(date) : "";
}

/** Newest first, by the instant each names (never by comparing the strings). */
export function newestFirst<T>(items: T[], at: (item: T) => string): T[] {
  return [...items].sort((a, b) => parseTimestamp(at(b)).getTime() - parseTimestamp(at(a)).getTime());
}

// --- one clock for every relative time on the page -------------------------

const TICK_MS = 30_000;
let clock = Date.now();
let timer: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();

function subscribe(onTick: () => void): () => void {
  listeners.add(onTick);
  if (timer === undefined) {
    clock = Date.now(); // the first reader after a quiet spell sees the time now, not when the page loaded
    timer = setInterval(() => {
      clock = Date.now();
      for (const listener of listeners) listener();
    }, TICK_MS);
  }
  return () => {
    listeners.delete(onTick);
    if (listeners.size === 0 && timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

/** Now, refreshed every 30 s for as long as something shows a relative time. */
export function useNow(): number {
  return useSyncExternalStore(
    subscribe,
    () => clock,
    () => clock,
  );
}
