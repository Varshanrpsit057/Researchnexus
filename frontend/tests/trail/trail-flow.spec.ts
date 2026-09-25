// spec: Phase 7 (Research Trail) critical flow.
//
// The trail under test is built by the backend's real trail pipeline:
// seed-trail-run.py persists a run's inputs (candidate papers, citation
// links, measured signals) and calls build_trail itself, so every rule,
// evidence span and confidence below is production output. Only the
// discovery job's start/poll is mocked (external search APIs are out of
// reach here), pointing the page at that real run. Creating the workspace,
// reading the trail, and every accept/reject run against the real backend.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPERS = path.join(__dirname, "..", "workspaces");
const FIXTURE = path.join(__dirname, "seed-trail-run.py");

const FOUNDATIONAL = "A paper about topic 1";
const SIMILAR = "Phase 7 Fixture: Retrieval-Augmented Generators Revisited";
const EXTENSION = "Phase 7 Fixture: Extending Parametric Memory with Dense Retrievers";
const COMPETING = "Phase 7 Fixture: A Competing Symbolic Approach";

function py(args: string[]) {
  execFileSync(PYTHON, args);
}

async function uploadSeed(page: Page): Promise<string> {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Browse for a file" }).click();
  await (await chooser).setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
  await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
  return page.url().split("/papers/")[1].split("?")[0];
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => msg.type() === "error" && errors.push(msg.text()));
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

const row = (page: Page, title: string) => page.getByRole("article", { name: title });
const tab = (page: Page, label: string, count: number) => page.getByRole("button", { name: `${label} ${count}`, exact: true });

test.describe("Research trail", () => {
  let seedId: string | null = null;

  test.afterEach(() => {
    if (seedId) {
      py([path.join(HELPERS, "cleanup-seeded-profile.py"), seedId]);
      py([FIXTURE, "restore", seedId]);
    }
    seedId = null;
  });

  test("a discovery run's trail shows each connection's evidence chain, filters, and decisions that persist", async ({ page }) => {
    // 1. Real upload and profile; a real run whose trail the real pipeline builds.
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Trail Flow Seed"]);
    const stamp = Date.now();
    const runId = `run_pw_trail_${stamp}`;
    py([FIXTURE, "seed", seedId, runId, String(stamp)]);

    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_trail", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_trail" } } }),
    );
    await page.route("**/api/v1/jobs/job_pw_trail", (route) =>
      route.fulfill({ json: { job_id: "job_pw_trail", status: "succeeded", progress: { stage: "done" }, result_ref: runId, error: null } }),
    );
    const consoleErrors = collectConsoleErrors(page);

    // 2. Discovery -> a workspace importing the run (nothing pre-selected, so all four stay to review).
    await page.goto(`/discover/${seedId}`);
    await expect(page.getByText(SIMILAR)).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Create workspace", exact: true }).click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 15_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

    // 3. Workspace -> Trail.
    await expect(page.getByRole("link", { name: /^Connections\s*:/ })).toContainText("4 awaiting review", { timeout: 10_000 });
    // with only the seed collected, the overview's next step is adding papers;
    // its Connections station is the way into the trail
    await page.getByRole("link", { name: /^Connections\s*:/ }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/trail$`));
    await expect(page.getByRole("heading", { level: 1, name: "Research trail" })).toBeVisible();
    await expect(tab(page, "To review", 4)).toHaveAttribute("aria-pressed", "true");
    for (const heading of ["Foundational", "Method extensions", "Similar", "Competing"]) {
      await expect(page.getByRole("heading", { level: 2, name: new RegExp(`^${heading}`) })).toBeVisible();
    }

    // 4. Paper -> evidence -> relationship -> conclusion, for a citation link.
    const foundational = row(page, FOUNDATIONAL);
    await foundational.getByRole("button", { name: /Show the evidence/ }).click();
    await expect(foundational).toContainText("The seed paper's reference list");
    await expect(foundational).toContainText("[1] A. Author et al. A paper about topic 1. Conf.");
    await expect(foundational).toContainText("The seed paper cites it.");
    await expect(foundational).toContainText("It came first: 2018, before the seed's 2021.");
    await expect(foundational).toContainText("The seed paper builds on this earlier work.");
    await expect(foundational).toContainText("Not checked by a language model, and high confidence needs that confirmation.");
    // the chain opens on the two papers, each linked
    await expect(foundational.getByRole("link", { name: /Synthetic Test Paper/ })).toHaveAttribute("href", `/seed/${seedId}`);

    // ...and for a similarity link: a verbatim abstract sentence and the measured value the rule fired on.
    const similar = row(page, SIMILAR);
    await similar.getByRole("button", { name: /Show the evidence/ }).click();
    await expect(similar).toContainText("Our study shows that retrieval augmented generation reduces hallucination");
    await expect(similar).toContainText("Its overall topic is 82% similar to the seed's (the rule needs 65%).");
    await similar.getByRole("button", { name: "Hide the evidence" }).click();

    // 5. Search runs over titles and quoted evidence; relationship filters narrow the list.
    await page.getByRole("searchbox", { name: "Search this trail" }).fill("symbolic reasoning");
    await expect(page.getByRole("article")).toHaveCount(1);
    await expect(row(page, COMPETING)).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).first().click();
    await page.getByRole("button", { name: "Method extensions 1" }).click();
    await expect(page.getByRole("article")).toHaveCount(1);
    await expect(row(page, EXTENSION)).toBeVisible();
    await page.getByRole("button", { name: "Method extensions 1" }).click();
    await expect(page.getByRole("article")).toHaveCount(4);

    // 6. Accept one, reject one, then accept the rest together.
    await page.getByRole("button", { name: `Accept the connection to ${FOUNDATIONAL}` }).click();
    await expect(tab(page, "To review", 3)).toBeVisible();
    await expect(tab(page, "Accepted", 1)).toBeVisible();
    await page.getByRole("button", { name: `Reject the connection to ${COMPETING}` }).click();
    await expect(tab(page, "Rejected", 1)).toBeVisible();
    await page.getByRole("checkbox", { name: `Select the connection to ${SIMILAR}` }).check();
    await page.getByRole("checkbox", { name: `Select the connection to ${EXTENSION}` }).check();
    await page.getByRole("button", { name: "Accept 2", exact: true }).click();
    await expect(tab(page, "To review", 0)).toBeVisible();
    await expect(page.getByText("Nothing is waiting for review.")).toBeVisible();

    // 7. It all persisted; a rejected connection can be restored for review.
    await page.reload();
    await expect(tab(page, "Accepted", 3)).toHaveAttribute("aria-pressed", "true", { timeout: 10_000 });
    await tab(page, "Rejected", 1).click();
    await page.getByRole("button", { name: `Restore the connection to ${COMPETING}` }).click();
    await expect(tab(page, "To review", 1)).toBeVisible();

    // 8. The overview reflects the review; the old trail URL forwards here.
    await page.goto(`/workspace/${workspaceId}`);
    await expect(page.getByRole("link", { name: /^Connections\s*:/ })).toContainText("1 awaiting review", { timeout: 10_000 });
    await page.goto(`/workspaces/${workspaceId}/trail`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/trail$`));

    expect(consoleErrors).toEqual([]);
  });

  test("a workspace started without discovery explains where connections come from, and a failed load offers a retry", async ({ page }) => {
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Trail Empty Seed"]);
    await page.reload();
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

    await page.goto(`/workspace/${workspaceId}/trail`);
    await expect(page.getByRole("heading", { name: "No connections yet" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("This one started from the seed paper alone.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Discover related papers" })).toHaveAttribute("href", `/discover/${seedId}`);

    // The server failing is simulated for this one response; the page's handling is what's tested.
    await page.route(`**/api/v1/workspaces/${workspaceId}/trail*`, (route) =>
      route.fulfill({ status: 500, json: { detail: { error: { code: "internal", message: "internal error" } } } }),
    );
    await page.reload();
    await expect(page.getByText("Could not load the research trail.")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  test("an unknown workspace gets an honest not-found state", async ({ page }) => {
    await page.goto("/workspace/ws_pw_trail_missing/trail");
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
  });
});
