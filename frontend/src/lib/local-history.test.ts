import { beforeEach, describe, expect, it, vi } from "vitest";
import { recordRecentPaper } from "./local-history";

const KEY = "researchnexus.recent-papers";

function stored(): { paperId: string; title: string; addedAt: string }[] {
  return JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
}

describe("recordRecentPaper", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("prepends new papers, most recent first", () => {
    recordRecentPaper({ paperId: "pap_1", title: "First", addedAt: "2026-01-01T00:00:00Z" });
    recordRecentPaper({ paperId: "pap_2", title: "Second", addedAt: "2026-01-02T00:00:00Z" });
    expect(stored().map((p) => p.paperId)).toEqual(["pap_2", "pap_1"]);
  });

  it("de-duplicates by paperId, moving the re-recorded paper back to the front", () => {
    recordRecentPaper({ paperId: "pap_1", title: "First", addedAt: "2026-01-01T00:00:00Z" });
    recordRecentPaper({ paperId: "pap_2", title: "Second", addedAt: "2026-01-02T00:00:00Z" });
    recordRecentPaper({ paperId: "pap_1", title: "First (reopened)", addedAt: "2026-01-03T00:00:00Z" });

    const all = stored();
    expect(all).toHaveLength(2);
    expect(all[0]).toMatchObject({ paperId: "pap_1", title: "First (reopened)" });
  });

  it("caps the list at 8 entries", () => {
    for (let i = 0; i < 10; i++) {
      recordRecentPaper({ paperId: `pap_${i}`, title: `Paper ${i}`, addedAt: new Date().toISOString() });
    }
    expect(stored()).toHaveLength(8);
    // the 2 oldest (pap_0, pap_1) were pushed out
    expect(stored().map((p) => p.paperId)).not.toContain("pap_0");
  });

  it("dispatches a researchnexus:recent-papers event so live views can refresh", () => {
    const handler = vi.fn();
    window.addEventListener("researchnexus:recent-papers", handler);
    recordRecentPaper({ paperId: "pap_1", title: "First", addedAt: "2026-01-01T00:00:00Z" });
    expect(handler).toHaveBeenCalledTimes(1);
    window.removeEventListener("researchnexus:recent-papers", handler);
  });
});
