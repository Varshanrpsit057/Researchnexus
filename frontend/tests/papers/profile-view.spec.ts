// spec: remediation Phase 6 -- the research profile as a reader gets it.
//
// A paper found by discovery and a profile stored the way the pipeline
// stored them before refinement existed (seed-old-profile.py, through the
// real repository): the abstract still carries its "Abstract" label and a
// publisher block, the metrics are bare names, a model is repeated as an
// entity. Everything checked here is what the real backend makes of it --
// no network mocking.
import path from "node:path";
import { execFileSync } from "node:child_process";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const seed = (mode: "seed" | "paper" | "clean", paperId: string) =>
  execFileSync(PYTHON, [path.join(__dirname, "seed-old-profile.py"), mode, paperId]);

test.describe("Research profile", () => {
  test("reads cleaned and summarised, with each metric's reported value and its evidence", async ({ page }) => {
    const id = `pap_pw_profile_${Date.now()}`;
    seed("seed", id);
    try {
      await page.goto(`/papers/${id}`);
      const profile = page.getByTestId("research-profile");
      await expect(profile).toContainText("Read from the abstract only");

      // 1. in brief: the paper's own sentences, no label, no publisher block
      const brief = page.getByTestId("profile-brief");
      await expect(brief).toContainText(
        "This paper proposes a face recognition attendance system for classrooms. Experiments on 40 students reveal a precision and recall of 96% and 93% respectively.",
      );
      await expect(brief).not.toContainText("Abstract");
      await brief.getByText("Read the full abstract").click();
      await expect(brief).toContainText("In modern educational institutions, attendance tracking is slow and error-prone.");
      await expect(brief).not.toContainText("ELSEVIER");
      await expect(brief).not.toContainText("Keywords:");

      // 2. metrics: a value only where the evidence states it, and which one is whose ("respectively")
      const metrics = page.getByTestId("profile-metrics");
      await expect(metrics.getByRole("row", { name: /^Precision/ })).toContainText("96%");
      await expect(metrics.getByRole("row", { name: /^Recall/ })).toContainText("93%");
      await expect(metrics.getByRole("row", { name: /^F1 score/ })).toContainText("No value in the evidence");
      await metrics.getByRole("button", { name: "Show the passage for Recall" }).click();
      await expect(metrics).toContainText("a precision and recall of 96% and 93% respectively");

      // 3. names read the same way, listed once; an item not found in the text is marked
      await expect(profile.getByRole("button", { name: "Face detection" })).toBeVisible();
      await expect(profile.getByText("face-api.js", { exact: true })).toHaveCount(1); // a model, not also "mentioned"
      await expect(profile.getByText("Guessed method", { exact: true })).toBeVisible();
      await expect(profile).toContainText("not found in the text");
      await profile.getByText("More about this paper").click();
      await expect(profile).toContainText("Education technology");

      // 4. the seed page shows the same profile the same way
      await page.goto(`/seed/${id}`);
      await expect(page.getByTestId("profile-metrics").getByRole("row", { name: /^Precision/ })).toContainText("96%");
      await expect(page.getByTestId("profile-brief")).not.toContainText("Abstract");
    } finally {
      seed("clean", id);
    }
  });

  test("a paper found by discovery offers an analysis of its abstract, and says what stops it", async ({ page }) => {
    const id = `pap_pw_found_${Date.now()}`;
    seed("paper", id);
    try {
      await page.goto(`/papers/${id}`);
      await expect(page.getByText("This paper was found by a search, so only its abstract is available.")).toBeVisible();
      // real backend: this test user has no working key
      await page.getByRole("button", { name: "Analyse the abstract" }).click();
      const failure = page.getByRole("alert").filter({ hasText: "No working language model key is saved yet." });
      await expect(failure).toBeVisible();
      await expect(failure.getByRole("link", { name: "Open Settings" })).toHaveAttribute("href", "/settings#models");
    } finally {
      seed("clean", id);
    }
  });
});
