// spec: Slice 4 (Research workspace) critical flow -- evidence navigation
// on the Graph page specifically (the Phase 8 graph at /workspace/[id]/graph;
// tests/graph/graph-flow.spec.ts covers the rest of that page). Overview/Papers/Trail's own real-backend
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
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

    const targetPaperId = `pap_pw_graph_${Date.now()}`;
    seedSecondPaperAndEdge(seedPaperId, targetPaperId, workspaceId);
    // the old Papers tab forwards to the overview's papers, where a paper is added by id
    await page.goto(`/workspaces/${workspaceId}/papers`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}#papers$`));
    await page.getByRole("button", { name: "Add papers" }).click();
    await page.getByLabel("Add by paper ID").fill(targetPaperId);
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.locator("#papers").getByText("A Playwright Fixture Related Paper")).toBeVisible({ timeout: 10_000 });

    // the old URL forwards to the graph page
    await page.goto(`/workspaces/${workspaceId}/graph`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/graph$`));
    const stage = page.getByTestId("graph-stage");
    await expect(stage).toHaveAttribute("data-phase", "settled", { timeout: 10_000 });
    await expect(page.getByText("2 papers in the workspace · 1 connection", { exact: true })).toBeVisible();
    // Point at the target paper's node (found by its accessible name, not a
    // hardcoded coordinate): it is a member, and joining accepted its edge.
    await stage.getByRole("button", { name: /^A Playwright Fixture Related Paper\. In this workspace\./ }).click();

    const panel = page.getByRole("complementary");
    await expect(panel.getByRole("link", { name: "Open paper" })).toHaveAttribute("href", `/papers/${targetPaperId}`);
    await expect(panel).toContainText("Accepted");
    // its connection opens on the real evidence behind it
    await expect(panel.getByText("a fixture evidence sentence for testing")).toBeVisible();
  });
});
