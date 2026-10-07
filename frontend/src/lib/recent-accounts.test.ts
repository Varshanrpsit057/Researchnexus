import { describe, expect, it } from "vitest";
import { isKnownAccount, withAccount, type RecentAccount } from "./recent-accounts";

describe("recent accounts", () => {
  const list: RecentAccount[] = [
    { email: "a@uni.edu", lastUsedAt: "2026-10-01T00:00:00Z" },
    { email: "b@uni.edu", lastUsedAt: "2026-09-01T00:00:00Z" },
  ];

  it("puts the account just used first, once whatever its case, and keeps five", () => {
    const next = withAccount(list, "  B@Uni.edu ", "2026-10-06T00:00:00Z");
    expect(next.map((a) => a.email)).toEqual(["b@uni.edu", "a@uni.edu"]);
    expect(next[0].lastUsedAt).toBe("2026-10-06T00:00:00Z");
    let many = list;
    for (let i = 0; i < 8; i++) many = withAccount(many, `x${i}@uni.edu`, "2026-10-06T00:00:00Z");
    expect(many).toHaveLength(5);
    expect(withAccount(list, "   ", "2026-10-06T00:00:00Z")).toBe(list);
  });

  it("knows an email used here before, whatever its case", () => {
    expect(isKnownAccount(list, "A@UNI.EDU")).toBe(true);
    expect(isKnownAccount(list, "c@uni.edu")).toBe(false);
  });
});
