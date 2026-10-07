// spec: remediation Phase 8 -- discovery says what it is doing, can be
// cancelled, is followed (never restarted) on return, and labels a partial
// run with what is missing.
//
// A real run's external conditions (Semantic Scholar rate-limiting half its
// requests, OpenAlex refusing) can't be had on demand, so seed-discover-job.py
// writes jobs and a saved run through the backend's own code: the progress and
// report come from the real DiscoveryProgress tracker, the failure text from
// the real job runner. Nothing on the network is mocked: the page starts
// discovery, polls, cancels and reads results through the real backend.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPER = path.join(__dirname, "seed-discover-job.py");
const PROFILE_HELPERS = path.join(__dirname, "..", "workspaces");
const EMAIL = "playwright@researchnexus.dev";

function helper(...args: string[]): string {
  return execFileSync(PYTHON, [HELPER, ...args]).toString().trim();
}

async function uploadSeed(page: Page): Promise<string> {
  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Browse for a file" }).click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
  await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
  const paperId = page.url().split("/papers/")[1].split("?")[0];
  execFileSync(PYTHON, [path.join(PROFILE_HELPERS, "seed-real-profile.py"), paperId, "Discovery Progress Seed Paper"]);
  return paperId;
}

test.describe("Discovery progress", () => {
  let seedId: string | null = null;
  const jobs: string[] = [];

  test.afterEach(() => {
    if (jobs.length > 0) helper("cleanup", ...jobs);
    jobs.length = 0;
    if (seedId) execFileSync(PYTHON, [path.join(PROFILE_HELPERS, "cleanup-seeded-profile.py"), seedId]);
    seedId = null;
  });

  test("a running discovery shows each step, search and source as it happens, and is followed rather than restarted", async ({ page }) => {
    seedId = await uploadSeed(page);
    const jobId = helper("running", seedId, EMAIL);
    jobs.push(jobId);

    // Reaching the page starts discovery -- and the backend hands back the
    // run of this seed already going instead of starting a second.
    await page.goto(`/discover/${seedId}`);
    await expect(page).toHaveURL(new RegExp(`\\?job=${jobId}$`));
    const panel = page.getByTestId("discovery-progress");
    await expect(panel.getByRole("status")).toHaveText("Searching external sources…");
    await expect(panel).toContainText("Built from the paper's profile");
    await expect(panel).toContainText("Found on Semantic Scholar; OpenAlex couldn't be asked");
    await expect(panel).toContainText("3 papers so far");
    await expect(panel).toContainText(/stops within \d+ s/); // the search step's real limit, never an estimate
    await expect(panel).toContainText("Keyword search · 3 so far");
    await expect(panel).toContainText("Recommendations · 2 found — OpenAlex's related works failed");
    const sources = page.getByTestId("discovery-sources");
    await expect(sources.getByText("4 answered · 4 refused (rate-limited)")).toBeVisible();
    await expect(sources.getByText("3 answered", { exact: true })).toBeVisible();
    await expect(page.getByTestId("discovery-preview")).toContainText("Phase 8 Fixture: Retrieval Signals for Related Work");
    await expect(panel).toContainText("Not ranked yet");

    // The page follows the run: moved on outside the page, it shows the next step.
    helper("advance", jobId);
    await expect(panel.getByRole("status")).toHaveText("Ranking candidates against the seed profile…", { timeout: 10_000 });
    await expect(panel).toContainText("Citations · 12 found — Stopped at its 30 s limit; the 12 papers it had found are kept");
    await expect(panel).toContainText("2 candidates saved");

    // A refresh picks the same run up again.
    await page.reload();
    await expect(page).toHaveURL(new RegExp(`\\?job=${jobId}$`));
    await expect(page.getByTestId("discovery-progress").getByRole("status")).toHaveText("Ranking candidates against the seed profile…");
  });

  test("cancelling stops the run for real", async ({ page }) => {
    seedId = await uploadSeed(page);
    const jobId = helper("running", seedId, EMAIL);
    jobs.push(jobId);

    await page.goto(`/discover/${seedId}?job=${jobId}`);
    await page.getByRole("button", { name: "Cancel discovery" }).click();
    await expect(page.getByTestId("discovery-ended")).toContainText("Discovery cancelled");
    await expect(page.getByTestId("discovery-ended")).toContainText("You stopped this run; nothing from it was saved.");
    await expect(page.getByRole("button", { name: "Start again" })).toBeVisible();
    const job = await (await page.request.get(`http://localhost:8000/api/v1/jobs/${jobId}`)).json();
    expect(job.status).toBe("cancelled");
  });

  test("a run that stopped responding, failed, or no longer exists says so and why", async ({ page }) => {
    seedId = await uploadSeed(page);
    const stale = helper("stale", seedId, EMAIL);
    const failed = helper("failed", seedId, EMAIL);
    jobs.push(stale, failed);

    await page.goto(`/discover/${seedId}?job=${stale}`);
    const ended = page.getByTestId("discovery-ended");
    await expect(ended).toContainText("Discovery was interrupted");
    await expect(ended).toContainText("The run stopped responding before it finished.");
    await expect(page.getByRole("button", { name: "Start again" })).toBeVisible();

    await page.goto(`/discover/${seedId}?job=${failed}`);
    await expect(ended).toContainText("Discovery failed");
    await expect(ended).toContainText("The discovery step failed: every source refused the request");
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();

    // a link to a run that no longer exists says so, instead of "Starting…" forever
    await page.goto(`/discover/${seedId}?job=job_pw_p8_missing`);
    await expect(ended).toContainText("This discovery run can't be found");
    await expect(page.getByRole("button", { name: "Start again" })).toBeVisible();
  });

  test("a partial run's results say what is missing, and how the search ran", async ({ page }) => {
    seedId = await uploadSeed(page);
    const stamp = Date.now();
    const runId = helper("run", seedId, `run_pw_p8_${stamp}`, `pap_pw_p8_a_${stamp}`, `pap_pw_p8_b_${stamp}`);

    await page.goto(`/discover/${seedId}?run=${runId}`);
    await expect(page.getByTestId("results-list").getByText("Phase 8 Fixture: Retrieval Signals for Related Work")).toBeVisible({ timeout: 10_000 });
    const incomplete = page.getByTestId("run-incomplete");
    await expect(incomplete).toContainText("Partial results: some of the search didn't finish");
    await expect(incomplete).toContainText("Citations ran out of time after 30 s; the 12 papers it had found are included.");
    await expect(incomplete).toContainText("Semantic Scholar refused 4 of 8 requests (rate-limited).");
    await expect(incomplete).toContainText("OpenAlex refused 1 of 1 requests (rate-limited).");
    // a capped run is not called incomplete: it says what it kept
    await expect(page.getByText("Kept the 2 papers with the most evidence of the 14 found; the rest weren't ranked.")).toBeVisible();

    await page.getByText("How this search ran").click();
    const details = page.locator("details", { hasText: "How this search ran" });
    await expect(details).toContainText("search sources · done · 30 s");
    await expect(details).toContainText("Citations: 12 (stopped at its limit) in 30 s");
    await expect(details).toContainText("Semantic Scholar: 4 answered · 4 refused (rate-limited)");
  });
});
