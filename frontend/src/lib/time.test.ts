import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime, formatLongDate, newestFirst, parseTimestamp, relativeTime } from "./time";

const at = (d: Date) => d.toISOString();

describe("parseTimestamp", () => {
  it("reads a backend time as the instant it names, whatever the browser's timezone", () => {
    const instant = Date.UTC(2026, 8, 27, 4, 11, 50, 409);
    expect(parseTimestamp("2026-09-27T04:11:50.409852Z").getTime()).toBe(instant);
    expect(parseTimestamp("2026-09-27T04:11:50.409852+00:00").getTime()).toBe(instant);
    expect(parseTimestamp("2026-09-27T09:41:50.409852+05:30").getTime()).toBe(instant);
    // no zone (an older row, SQLite's own text): UTC, never the browser's local time
    expect(parseTimestamp("2026-09-27T04:11:50.409852").getTime()).toBe(instant);
    expect(parseTimestamp("2026-09-27 04:11:50.409852").getTime()).toBe(instant);
  });
});

describe("relativeTime", () => {
  const now = Date.UTC(2026, 8, 27, 12, 0, 0);
  const ago = (ms: number) => at(new Date(now - ms));

  it("counts down, never up", () => {
    expect(relativeTime(ago(30_000), now)).toBe("just now"); // was "1 min ago": rounded up
    expect(relativeTime(ago(90_000), now)).toBe("1 min ago");
    expect(relativeTime(ago(59 * 60_000 + 59_000), now)).toBe("59 min ago");
    expect(relativeTime(ago(90 * 60_000), now)).toBe("1 h ago"); // was "2 h ago"
    expect(relativeTime(ago(23 * 3_600_000 + 59 * 60_000), now)).toBe("23 h ago");
  });

  it("calls a clock that runs a little ahead 'just now', and an unreadable time nothing", () => {
    expect(relativeTime(ago(-45_000), now)).toBe("just now");
    expect(relativeTime("not a time", now)).toBe("");
  });

  it("says yesterday only for the reader's own yesterday", () => {
    // built from the reader's local calendar, so this holds in every timezone
    const local = (d: number, h: number, m = 0) => new Date(2026, 8, d, h, m).getTime();
    const lateLastNight = at(new Date(local(26, 23)));
    expect(relativeTime(lateLastNight, local(27, 1))).toBe("2 h ago");
    expect(relativeTime(at(new Date(local(26, 0, 30))), local(27, 1))).toBe("yesterday");
    // 26 hours, but two calendar days back: the old rule (under 48 h) said "yesterday"
    expect(relativeTime(at(new Date(local(25, 23))), local(27, 1))).toBe("2 days ago");
    expect(relativeTime(at(new Date(local(21, 9))), local(27, 10))).toBe("6 days ago");
    expect(relativeTime(at(new Date(local(19, 9))), local(27, 10))).toMatch(/Sep 19|19 Sep/);
  });
});

describe("absolute times, in the reader's timezone", () => {
  const backend = "2026-09-27T04:11:50"; // 04:11 UTC, as SQLite hands it back

  it("shows the same instant as each reader's own clock and day", () => {
    expect(formatDateTime(backend, { timeZone: "UTC", locale: "en-US" })).toMatch(/Sep 27, 2026.*4:11/);
    expect(formatDateTime(backend, { timeZone: "Asia/Kolkata", locale: "en-US" })).toMatch(/Sep 27, 2026.*9:41/);
    // for a reader in California it is still the evening before
    expect(formatDateTime(backend, { timeZone: "America/Los_Angeles", locale: "en-US" })).toMatch(/Sep 26, 2026.*9:11/);
    expect(formatDate(backend, { timeZone: "America/Los_Angeles", locale: "en-US", now: Date.UTC(2026, 8, 27) })).toBe("Sep 26");
    expect(formatLongDate(backend, { timeZone: "Asia/Kolkata", locale: "en-US" })).toBe("September 27, 2026");
  });

  it("gives the year only outside the current one", () => {
    expect(formatDate("2026-03-02T10:00:00Z", { timeZone: "UTC", locale: "en-US", now: Date.UTC(2026, 8, 27) })).toBe("Mar 2");
    expect(formatDate("2025-03-02T10:00:00Z", { timeZone: "UTC", locale: "en-US", now: Date.UTC(2026, 8, 27) })).toBe("Mar 2, 2025");
  });

  it("returns nothing for a time it can't read", () => {
    expect(formatDate("soon")).toBe("");
    expect(formatDateTime("soon")).toBe("");
    expect(formatLongDate("soon")).toBe("");
  });
});

describe("newestFirst", () => {
  it("orders by the instant, not by the text", () => {
    const rows = [
      { id: "a", at: "2026-09-27T04:00:00Z" },
      { id: "b", at: "2026-09-27T09:00:00+05:30" }, // 03:30 UTC: the oldest, though its text sorts last
      { id: "c", at: "2026-09-27 04:30:00" }, // 04:30 UTC
    ];
    expect(newestFirst(rows, (r) => r.at).map((r) => r.id)).toEqual(["c", "a", "b"]);
  });
});
