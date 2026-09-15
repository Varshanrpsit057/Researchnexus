// spec: Slice 3 (Explore -> Curate) critical flow.
//
// Creating a workspace requires the seed paper to have a genuinely
// *persisted* profile (the real backend's own SeedNotAnalyzed check) --
// unlike Slice 1/2, that cannot be satisfied by mocking a response at the
// network layer, since the check runs server-side against real stored
// data. `analyze` is LLM-gated and no working BYOK key exists in this
// environment, so two small Python helpers seed a profile and a second
// paper + trail edge directly through the same repository layer the real
// `analyze`/`discover-related` pipelines write through (see the .py files
// beside this spec). Every UI interaction from create-workspace onward --
// creating the workspace, adding a paper by id, viewing the trail, and
// accepting/rejecting an edge -- then runs against the real backend with
// no mocking at all.
//
// The dev database is one persistent file shared by every spec and every
// run, not reset per test -- found live, the hard way: leaving the seeded
// profile in place after this test broke analyze-flow.spec.ts and
// discover-flow.spec.ts, both of which assume the shared fixture PDF is
// still unanalyzed. `afterEach` below always removes it, pass or fail.
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

test.describe("Explore -> Curate", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) cleanupSeededProfile(seededPaperId);
    seededPaperId = null;
  });

  test("creating a workspace, adding a paper, and reviewing the trail all persist for real", async ({ page }) => {
    // 1. Real upload, then unblock workspace creation the only way this
    //    environment allows (see file header).
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    const seedPaperId = page.url().split("/papers/")[1].split("?")[0];
    seededPaperId = seedPaperId;
    // The paper's own title comes from real PDF parsing, not from the
    // seeded profile (which carries its own, separate `title` field) --
    // read it back from the page rather than asserting a literal string.
    seedProfile(seedPaperId, "Curate Flow Seed Paper");
    await page.reload();
    await expect(page.getByRole("heading", { name: "Research profile" })).toBeVisible();
    const paperTitle = await page.getByRole("heading", { level: 1 }).innerText();

    // 2. Real create-workspace call (no related papers pre-selected --
    //    discovery itself is Slice 2's concern and is network-blocked
    //    here). This is also a real-flow check in its own right: before
    //    this session's Slice 3 pass, the only "Create workspace" trigger
    //    lived inside the discovery-results view, so a failed or
    //    not-yet-run discovery blocked reaching a workspace at all.
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    const dialog = page.getByRole("dialog", { name: "Create a workspace" });
    await expect(dialog.getByText(`Only ${paperTitle}`, { exact: false })).toBeVisible();
    await dialog.getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspaces\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspaces/")[1].split("/")[0].split("?")[0];

    // 3. Seed a second real paper plus a *pending* trail edge to it.
    const targetPaperId = `pap_pw_curate_${Date.now()}`;
    seedSecondPaperAndEdge(seedPaperId, targetPaperId, workspaceId);

    // 4. Add it via the real UI form -- exercises the real add_papers
    //    endpoint, which is also expected to auto-accept any trail edge
    //    targeting the paper it just added (found reading
    //    services/workspace/pipeline.py's `_accept_edges_for_target`; the
    //    "Create workspace" dialog copy was silently wrong about this
    //    until this session's Slice 3 pass -- verifying it for real here).
    await page.goto(`/workspaces/${workspaceId}/papers`);
    await page.getByLabel("Add a paper by ID").fill(targetPaperId);
    await page.getByRole("button", { name: "Add" }).click();
    await expect(page.getByText(targetPaperId)).toBeVisible({ timeout: 5_000 });

    // 5. The trail edge to that paper should already read ACCEPTED, not
    //    PENDING -- the real, live proof of the auto-accept behavior.
    await page.goto(`/workspaces/${workspaceId}/trail`);
    await expect(page.getByText("A Playwright Fixture Related Paper")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("accepted", { exact: true })).toBeVisible();
    await expect(page.getByText("Fixture Reference 2024")).toBeVisible();

    // 6. Reject it for real, then confirm the workspace-level edge count
    //    (a *separate* SWR cache key on the Overview page) reflects the
    //    change -- edges are counted "not rejected", so this is a real
    //    cross-page consistency check, not just a Trail-local one.
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    // The default "Pending + accepted" filter hides a just-rejected edge
    // outright -- switch to the Rejected filter to see its withdrawn stamp.
    await page.getByRole("button", { name: "Rejected", exact: true }).click();
    await expect(page.getByText("withdrawn", { exact: true })).toBeVisible();
    await page.goto(`/workspaces/${workspaceId}`);
    await expect(page.getByText("0", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("trail edges")).toBeVisible();
  });
});
