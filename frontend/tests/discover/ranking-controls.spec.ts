// spec: remediation Phases 9-10 -- the ranking criteria are real controls:
// set before discovery they reach the real job, and on a saved run they
// re-rank it for real; "Why this rank" shows what each signal added.
//
// Nothing on the network is mocked. The discovery started here is a real job
// against the real sources, cancelled at once (only its criteria matter); the
// re-ranked run was ranked by the backend's own ranking pipeline
// (seed-discover-job.py ranked-run).
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPER = path.join(__dirname, "seed-discover-job.py");
const PROFILE_HELPERS = path.join(__dirname, "..", "workspaces");

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
  execFileSync(PYTHON, [path.join(PROFILE_HELPERS, "seed-real-profile.py"), paperId, "Ranking Controls Seed Paper"]);
  return paperId;
}

test.describe("Ranking controls", () => {
  let seedId: string | null = null;
  const jobs: string[] = [];

  test.afterEach(async ({ page }) => {
    await page.evaluate(() => window.localStorage.removeItem("researchnexus.pref.rankingCriteria"));
    if (jobs.length > 0) helper("cleanup", ...jobs);
    jobs.length = 0;
    if (seedId) execFileSync(PYTHON, [path.join(PROFILE_HELPERS, "cleanup-seeded-profile.py"), seedId]);
    seedId = null;
  });

  test("criteria set before discovery are the ones the real job ranks by", async ({ page }) => {
    seedId = await uploadSeed(page);
    await page.goto(`/seed/${seedId}`);
    await page.getByText("Ranking criteria: the default weights").click();
    const recency = page.getByRole("slider", { name: "Recency" });
    await recency.focus();
    await page.keyboard.press("End"); // recency 100
    await expect(page.getByText("Ranking criteria: your weights")).toBeVisible();
    await expect(page.getByTestId("ranking-criteria")).toContainText("48% of the score"); // 100 of 209

    // all off can't be ranked by: discovery can't start, and it isn't saved
    for (const name of ["Topic similarity", "Research problem", "Methods", "Datasets", "Citation links", "Recency", "Preferred publisher"]) {
      await page.getByRole("slider", { name }).focus();
      await page.keyboard.press("Home");
    }
    await expect(page.getByTestId("ranking-criteria").getByRole("alert")).toHaveText("At least one criterion has to count.");
    await expect(page.getByRole("link", { name: "Start discovery" })).toHaveCount(0);
    await recency.focus();
    await page.keyboard.press("End");

    const started = page.waitForRequest((r) => r.url().endsWith("/discover-related") && r.method() === "POST");
    await page.getByRole("link", { name: "Start discovery" }).click();
    const body = (await started).postDataJSON();
    expect(body.criteria).toEqual({ topic: 0, problem: 0, methods: 0, datasets: 0, citations: 0, recency: 100, publisher: 0 });

    await expect(page).toHaveURL(/\?job=job_/, { timeout: 10_000 });
    const jobId = new URL(page.url()).searchParams.get("job") as string;
    jobs.push(jobId);
    await page.getByRole("button", { name: "Cancel discovery" }).click();
    await expect(page.getByTestId("discovery-ended")).toContainText("Discovery cancelled");
    const job = await (await page.request.get(`http://localhost:8000/api/v1/jobs/${jobId}`)).json();
    expect(job.progress.ranking_criteria).toEqual(body.criteria);
  });

  test("re-weighing a saved run re-ranks it for real and explains the new order", async ({ page }) => {
    seedId = await uploadSeed(page);
    const stamp = Date.now();
    const runId = helper("ranked-run", seedId, `run_pw_p9_${stamp}`, `pap_pw_p9_cited_${stamp}`, `pap_pw_p9_new_${stamp}`);
    await page.goto(`/discover/${seedId}?run=${runId}`);

    // With no relevance model and a seed profile naming no datasets, the new
    // paper has only its recency signal, so all its weight is recency's: it
    // ranks first, and its detail says what couldn't be computed.
    const list = page.getByTestId("results-list");
    const rows = list.getByRole("listitem");
    await expect(rows.first()).toContainText("Phase 9 Fixture: A Brand New Paper", { timeout: 10_000 });
    const detail = page.getByTestId("result-detail");
    await expect(detail).toContainText("Why this rank");
    await expect(detail.getByRole("row", { name: /Recency/ }).first()).toBeVisible();
    await expect(detail).toContainText("Not computed for this paper:");
    await expect(detail).toContainText("Ranked by the initial weights");

    await page.getByRole("button", { name: "Ranking criteria" }).click();
    const rerank = page.getByRole("button", { name: "Re-rank results" });
    await expect(rerank).toBeDisabled(); // nothing changed yet
    await page.getByRole("slider", { name: "Citation links" }).focus();
    await page.keyboard.press("End");
    await page.getByRole("slider", { name: "Recency" }).focus();
    await page.keyboard.press("Home");
    await rerank.click();

    // recency no longer counts, citation links do: the paper the seed cites leads
    await expect(rows.first()).toContainText("Phase 9 Fixture: An Older Paper The Seed Cites", { timeout: 10_000 });
    await expect(page.getByRole("button", { name: "Ranking criteria: yours" })).toBeVisible();
    await list.locator('[data-row="0"]').click();
    await expect(detail.getByRole("row", { name: /Citation link to the seed/ })).toBeVisible();
    await expect(detail).toContainText("Ranked by your weights");

    // the new order is the saved one, and the next discovery ranks the same way
    await page.reload();
    await expect(page.getByTestId("results-list").getByRole("listitem").first()).toContainText("An Older Paper The Seed Cites", { timeout: 10_000 });
    const saved = await page.evaluate(() => JSON.parse(window.localStorage.getItem("researchnexus.pref.rankingCriteria") ?? "null"));
    expect(saved.citations).toBe(100);
    expect(saved.recency).toBe(0);
  });

  test("the results can be searched, filtered and walked with the keyboard", async ({ page }) => {
    seedId = await uploadSeed(page);
    const stamp = Date.now();
    const runId = helper("ranked-run", seedId, `run_pw_p10_${stamp}`, `pap_pw_p10_cited_${stamp}`, `pap_pw_p10_new_${stamp}`);
    await page.goto(`/discover/${seedId}?run=${runId}`);
    const list = page.getByTestId("results-list");
    await expect(list.getByRole("listitem")).toHaveCount(2, { timeout: 10_000 });

    await page.getByRole("searchbox").fill("brand new");
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect(page.getByText("1 of 2 papers")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await page.getByRole("combobox", { name: "Found by" }).selectOption("citation");
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect(list).toContainText("An Older Paper The Seed Cites");
    await page.getByRole("combobox", { name: "Found by" }).selectOption("all");

    await page.getByRole("combobox", { name: "Sort by" }).selectOption("newest");
    await expect(list.getByRole("listitem").first()).toContainText("A Brand New Paper");

    // arrow keys move the focus down the list; the detail follows it
    await list.locator('[data-row="0"]').focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("result-detail").getByRole("heading", { level: 2 })).toHaveText("Phase 9 Fixture: An Older Paper The Seed Cites");
  });
});
