// spec: Phase 6 (Research Workspace) critical flow.
//
// Discovery's external sources are unreachable from this environment, so a
// genuine completed discovery run -- two ranked related papers plus a
// pending trail edge to each -- is persisted through the backend's own
// repository layer (seed-discovery-run.py), and only the discovery job's
// start/poll is mocked to hand the page that real run id. Everything else
// runs against the real backend with no mocking: the /related listing,
// creating the workspace with the run imported, adding a selected paper,
// the overview's data, adding and removing papers from the overview, and
// the trail edges being accepted as papers join.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPERS = path.join(__dirname, "..", "workspaces");

const FIRST_TITLE = "Phase 6 Fixture: A Dense Retrieval Baseline";
const SECOND_TITLE = "Phase 6 Fixture: A Late-Interaction Reranker";

function seedProfile(paperId: string, title: string) {
  execFileSync(PYTHON, [path.join(HELPERS, "seed-real-profile.py"), paperId, title]);
}

function cleanupSeededProfile(paperId: string) {
  execFileSync(PYTHON, [path.join(HELPERS, "cleanup-seeded-profile.py"), paperId]);
}

function seedDiscoveryRun(seedPaperId: string, runId: string, firstId: string, secondId: string) {
  execFileSync(PYTHON, [path.join(__dirname, "seed-discovery-run.py"), seedPaperId, runId, firstId, secondId]);
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

/**
 * The research-path stage link whose label starts with `label`. Chromium's
 * accessible name puts a space before the colon (the state text is an
 * absolutely positioned sr-only span), hence the `\s*`.
 */
function station(page: Page, label: string) {
  return page.getByRole("link", { name: new RegExp(`^${label}\\s*:`) });
}

test.describe("Research workspace", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) cleanupSeededProfile(seededPaperId);
    seededPaperId = null;
  });

  test("a real discovery run becomes a workspace whose overview shows real data, and papers can be added and removed", async ({ page }) => {
    // 1. Real upload, a real persisted profile, and a real completed run.
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    const seedId = page.url().split("/papers/")[1].split("?")[0];
    seededPaperId = seedId;
    seedProfile(seedId, "Workspace Flow Seed Paper");
    const stamp = Date.now();
    const runId = `run_pw_ws_${stamp}`;
    const firstId = `pap_pw_ws_a_${stamp}`;
    const secondId = `pap_pw_ws_b_${stamp}`;
    seedDiscoveryRun(seedId, runId, firstId, secondId);

    // 2. Mock only the job start/poll, pointing at the real run.
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_ws", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_ws" } } }),
    );
    await page.route("**/api/v1/jobs/job_pw_ws", (route) =>
      route.fulfill({ json: { job_id: "job_pw_ws", status: "succeeded", progress: { stage: "done" }, result_ref: runId, error: null } }),
    );

    const consoleErrors = collectConsoleErrors(page);

    // 3. Real ranked results from the real /related endpoint.
    await page.goto(`/discover/${seedId}`);
    await expect(page.getByText(FIRST_TITLE)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SECOND_TITLE)).toBeVisible();

    // 4. Select the top result and create the workspace for real.
    await page.getByRole("button", { name: `Select ${FIRST_TITLE}` }).click();
    await page.getByRole("button", { name: /Create workspace with 1 paper/ }).click();
    const dialog = page.getByRole("dialog", { name: "Create a workspace" });
    await dialog.getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 15_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

    // 5. The overview shows the real workspace.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Discovery results" })).toHaveAttribute("href", `/discover/${seedId}?run=${runId}`);
    await expect(page.getByRole("heading", { name: /^Papers\s*2$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: FIRST_TITLE })).toBeVisible();
    await expect(page.getByText("Added from discovery · ranked #1, high confidence · abstract only")).toBeVisible();
    // Importing the run attached both trail edges; adding the first paper
    // accepted its edge, the second is still pending review.
    await expect(station(page, "Connections")).toContainText("2 connections");
    await expect(station(page, "Connections")).toContainText("1 awaiting review");
    await expect(page.getByRole("link", { name: "Review connections" })).toHaveAttribute("href", `/workspaces/${workspaceId}/trail`);
    await expect(station(page, "Comparison")).toContainText("Not run yet");
    await expect(page.getByRole("link", { name: /^Research trail/ })).toHaveAttribute("href", `/workspaces/${workspaceId}/trail`);
    await expect(page.getByRole("link", { name: /^Research graph/ })).toHaveAttribute("href", `/workspaces/${workspaceId}/graph`);
    await expect(page.getByRole("link", { name: /^Citations/ })).toHaveAttribute("href", `/workspaces/${workspaceId}/citations`);
    await expect(page.getByRole("link", { name: "Ask this workspace" })).toHaveAttribute("href", `/workspaces/${workspaceId}/chat`);

    // 6. Add the remaining result from the workspace's own run.
    await page.getByRole("button", { name: "Add papers" }).click();
    await expect(page.getByRole("heading", { name: "From this workspace's discovery run" })).toBeVisible();
    const addSelected = page.getByRole("button", { name: /^(Select papers to add|Add \d+ papers?)$/ });
    await expect(addSelected).toBeDisabled(); // nothing chosen yet
    await page.getByRole("checkbox", { name: new RegExp(SECOND_TITLE) }).check();
    await expect(addSelected).toHaveText("Add 1 paper");
    await addSelected.click();
    await expect(page.getByRole("link", { name: SECOND_TITLE })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("heading", { name: /^Papers\s*3$/ })).toBeVisible();
    await expect(page.getByText("Every paper from the discovery run is already in this workspace.")).toBeVisible();
    // Joining the workspace accepted that paper's pending edge.
    await expect(station(page, "Connections")).toContainText("All reviewed", { timeout: 10_000 });
    await page.getByRole("button", { name: "Done adding" }).click();

    // 7. Remove it again, with an inline confirmation; the seed can't be removed.
    await expect(page.getByRole("button", { name: /Remove .* from workspace/ })).toHaveCount(2);
    await page.getByRole("button", { name: `Remove ${SECOND_TITLE} from workspace` }).click();
    await expect(page.getByText("Remove from workspace?")).toBeVisible();
    await page.getByRole("button", { name: "Remove", exact: true }).click();
    await expect(page.getByRole("link", { name: SECOND_TITLE })).toHaveCount(0, { timeout: 10_000 });
    await expect(page.getByRole("heading", { name: /^Papers\s*2$/ })).toBeVisible();

    // 8. It persisted: a reload shows the same real state.
    await page.reload();
    await expect(page.getByRole("heading", { name: /^Papers\s*2$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: FIRST_TITLE })).toBeVisible();

    // 9. The old overview URL forwards here.
    await page.goto(`/workspaces/${workspaceId}`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}$`));

    expect(consoleErrors).toEqual([]);
  });

  test("shows an honest not-found state for a workspace that doesn't exist", async ({ page }) => {
    await page.goto("/workspace/ws_pw_does_not_exist");
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: "All workspaces" })).toHaveAttribute("href", "/workspaces");
  });

  test("a server failure shows a retryable error instead of a blank page", async ({ page }) => {
    // The real backend can't be made to fail on demand, so this one
    // response is mocked; the page's own error handling is what's tested.
    await page.route("**/api/v1/workspaces/ws_pw_server_error", (route) =>
      route.fulfill({ status: 500, json: { detail: { error: { code: "internal", message: "internal error" } } } }),
    );
    await page.goto("/workspace/ws_pw_server_error");
    await expect(page.getByRole("heading", { name: "Could not load this workspace" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("The server hit an error while loading it.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});
