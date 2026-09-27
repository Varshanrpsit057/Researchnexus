"use client";

import { formatDate, formatDateTime, formatLongDate, parseTimestamp, relativeTime, useNow } from "@/lib/time";

type Style = "relative" | "date" | "long" | "datetime";

/**
 * A backend timestamp, shown in the reader's own time (lib/time.ts). A
 * relative one ("5 min ago") keeps itself current; every one carries the
 * exact local moment as its tooltip and a machine-readable `dateTime`.
 */
export function Timestamp({ at, style = "relative", className }: { at: string; style?: Style; className?: string }) {
  const now = useNow();
  const date = parseTimestamp(at);
  if (Number.isNaN(date.getTime())) return null;
  const text =
    style === "relative"
      ? relativeTime(at, now)
      : style === "date"
        ? formatDate(at, { now })
        : style === "long"
          ? formatLongDate(at)
          : formatDateTime(at);
  return (
    <time dateTime={date.toISOString()} title={formatDateTime(at)} className={className}>
      {text}
    </time>
  );
}
