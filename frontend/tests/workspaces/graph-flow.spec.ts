// spec: Slice 4 (Research workspace) critical flow -- evidence navigation
// on the Graph page specifically. Overview/Papers/Trail's own real-backend
// coverage lives in curate-flow.spec.ts; this spec is scoped to what that
// one doesn't reach: selecting a graph node must lead somewhere -- to the
// paper itself, and to the actual evidence behind a relationship -- not
// just show a label. Reuses curate-flow's seeding helpers (see that file's
// header for why real seeding, not mocking, is used here) and its
// afterEach cleanup discipline (the dev database is one persistent file
// shared by every spec).
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;

function seedProfile(paperId: string, title: string) {
  execFileSync(PYTHON, [path.join(__dirname, "seed-real-profile.py"), paperId, title]);
}

function seedSecondPaperAndEdge(seedPaperId: string, targetPaperId: string, workspaceId: string) {
  execFileSync(PYTHON, [path.join(__dirname, "seed-second-paper-and-edge.py"), seedPaperId, targetPaperId, workspaceId]);
}

function cleanupSeededProfile(paperId: string) {
  execFileSync(PYTHON, [path.join(__dirname, "cleanup-seeded-profile.py"), paperId]);
}

test.describe("Research workspace -> Graph evidence navigation", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) cleanupSeededProfile(seededPaperId);
    seededPaperId = null;
  });

  test("selecting a graph node links to its paper and discloses the real evidence behind its connection", async ({ page }) => {
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    const seedPaperId = page.url().split("/papers/")[1].split("?")[0];
    seededPaperId = seedPaperId;
    seedProfile(seedPaperId, "Graph Flow Seed Paper");
    await page.reload();

    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspaces\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspaces/")[1].split("/")[0].split("?")[0];

    const targetPaperId = `pap_pw_graph_${Date.now()}`;
    seedSecondPaperAndEdge(seedPaperId, targetPaperId, workspaceId);
    await page.goto(`/workspaces/${workspaceId}/papers`);
    await page.getByLabel("Add a paper by ID").fill(targetPaperId);
    await page.getByRole("button", { name: "Add" }).click();
    await expect(page.getByText(targetPaperId)).toBeVisible({ timeout: 5_000 });

    await page.goto(`/workspaces/${workspaceId}/graph`);
    await expect(page.getByText("2 nodes")).toBeVisible({ timeout: 5_000 });
    // Click the target paper's own node (its dot, drawn at the layout's
    // computed position -- select via the accessible role/name instead of
    // a hardcoded coordinate).
    await page.getByRole("button", { name: /Fixture Related Paper/ }).click();

    const link = page.getByRole("link", { name: "View paper" });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", `/papers/${targetPaperId}`);

    await page.getByText(/evidence span/).click();
    await expect(page.getByText("a fixture evidence sentence for testing")).toBeVisible();
  });
});
