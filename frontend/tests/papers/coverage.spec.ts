// spec: remediation Phase 7 -- what text a paper is read from, and getting more.
//
// Papers found by discovery (seed-old-profile.py, through the real
// repository). Looking for their full text runs against the real backend:
// these fixtures carry no DOI or arXiv id, so the real answer -- "no
// identifier to look it up by" -- comes back without a download.
import path from "node:path";
import { execFileSync } from "node:child_process";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const seed = (mode: "paper" | "failed" | "clean", paperId: string) =>
  execFileSync(PYTHON, [path.join(__dirname, "seed-old-profile.py"), mode, paperId]);

test.describe("Full-text coverage", () => {
  test("a paper with only its abstract says so, and looking for its full text says why there is none", async ({ page }) => {
    const id = `pap_pw_cov_${Date.now()}`;
    seed("paper", id);
    try {
      await page.goto(`/papers/${id}`);
      const coverage = page.getByTestId("coverage");
      await expect(coverage).toContainText("Abstract only");
      await expect(coverage).toContainText("Only its abstract is available; its full text hasn't been looked for yet.");
      await coverage.getByRole("button", { name: "Get the full text" }).click();
      await expect(coverage).toContainText("No full text could be found.");
      await expect(coverage).toContainText("it has no DOI or arXiv id to look its full text up by.");
      await expect(coverage.getByRole("button", { name: "Look again" })).toBeVisible();
      // the seed page says the same
      await page.goto(`/seed/${id}`);
      await expect(page.getByTestId("coverage")).toContainText("Abstract only");
    } finally {
      seed("clean", id);
    }
  });

  test("a failed retrieval names its reason, keeps the abstract, and can be tried again", async ({ page }) => {
    const id = `pap_pw_cov_failed_${Date.now()}`;
    seed("failed", id);
    try {
      await page.goto(`/papers/${id}`);
      const coverage = page.getByTestId("coverage");
      await expect(coverage).toContainText("Retrieval failed");
      await expect(coverage).toContainText(
        "Its full text was found but couldn't be used: the source refused the download (HTTP 403). Its abstract is used meanwhile.",
      );
      await expect(coverage.getByRole("button", { name: "Try again" })).toBeVisible();
    } finally {
      seed("clean", id);
    }
  });
});
