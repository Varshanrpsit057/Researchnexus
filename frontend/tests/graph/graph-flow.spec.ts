// spec: Phase 8 (Research Graph) critical flow.
//
// The graph under test is the backend's real projection of a real trail:
// seed-trail-run.py (Phase 7) persists a discovery run's inputs and runs the
// real trail pipeline over them, so every node, edge type, review state and
// evidence span below is production output. Only the discovery job's
// start/poll is mocked (external search APIs are out of reach here).
// Creating the workspace, reading the graph, and every accept / add /
// reject made from the graph run against the real backend.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPERS = path.join(__dirname, "..", "workspaces");
const FIXTURE = path.join(__dirname, "..", "trail", "seed-trail-run.py");

const SEED = "Synthetic Test Paper";
const FOUNDATIONAL = "A paper about topic 1";
const SIMILAR = "Phase 7 Fixture: Retrieval-Augmented Generators Revisited";
const EXTENSION = "Phase 7 Fixture: Extending Parametric Memory with Dense Retrievers";
const COMPETING = "Phase 7 Fixture: A Competing Symbolic Approach";

const py = (args: string[]) => execFileSync(PYTHON, args);
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

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

const stage = (page: Page) => page.getByTestId("graph-stage");
/** Every paper node: an accessible button named "<title>. <standing>. <year>. <connections>". */
const nodes = (page: Page) => stage(page).getByRole("button", { name: /\. (Seed paper|In this workspace|Connected, not in this workspace)\. / });
const node = (page: Page, title: string) =>
  stage(page).getByRole("button", { name: new RegExp(`${esc(title)}.*\\. (Seed paper|In this workspace|Connected, not in this workspace)\\. `) });
const panel = (page: Page) => page.getByRole("complementary");
const counts = (page: Page, text: string) => page.getByText(text, { exact: true });

/** Select a paper from the keyboard, the way a screen-reader or keyboard user would. */
async function openNode(page: Page, title: string) {
  await node(page, title).focus();
  await page.keyboard.press("Enter");
  await expect(panel(page).getByRole("heading", { level: 2 })).toContainText(title);
}

test.describe("Research graph", () => {
  let seedId: string | null = null;

  test.afterEach(() => {
    if (seedId) {
      py([path.join(HELPERS, "cleanup-seeded-profile.py"), seedId]);
      py([FIXTURE, "restore", seedId]);
    }
    seedId = null;
  });

  test("the background condenses into the workspace's graph, and every connection can be explored, reviewed and followed", async ({ page }) => {
    // 1. A real run whose trail the real pipeline builds (see seed-trail-run.py).
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Graph Flow Seed"]);
    const stamp = Date.now();
    const runId = `run_pw_graph_${stamp}`;
    py([FIXTURE, "seed", seedId, runId, `g${stamp}`]);
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_graph", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_graph" } } }),
    );
    await page.route("**/api/v1/jobs/job_pw_graph", (route) =>
      route.fulfill({ json: { job_id: "job_pw_graph", status: "succeeded", progress: { stage: "done" }, result_ref: runId, error: null } }),
    );
    const consoleErrors = collectConsoleErrors(page);

    // 2. Discovery -> a workspace importing the run: the seed alone, four connections to review.
    await page.goto(`/discover/${seedId}`);
    await expect(page.getByText(SIMILAR)).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Create workspace", exact: true }).click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 15_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

    // 3. Workspace -> Graph. The background morphs into the graph, which then settles.
    await page.getByRole("link", { name: /^Research graph/ }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/graph$`));
    await expect(page.getByRole("heading", { level: 1, name: "Research graph" })).toBeVisible();
    await expect(stage(page)).toHaveAttribute("data-phase", "intro", { timeout: 10_000 });
    await expect(page.getByTestId("constellation")).toHaveAttribute("data-mode", "graph");
    await expect(stage(page)).toHaveAttribute("data-phase", "settled", { timeout: 10_000 });
    await expect(counts(page, "1 paper in the workspace · 4 connected · 4 connections · 4 to review")).toBeVisible();
    await expect(nodes(page)).toHaveCount(5);
    // time runs left to right: the foundational paper predates the seed, the extension follows it
    const x = async (title: string) => (await node(page, title).boundingBox())!.x;
    expect(await x(FOUNDATIONAL)).toBeLessThan(await x(SEED));
    expect(await x(EXTENSION)).toBeGreaterThan(await x(SEED));
    for (const year of ["2018", "2021", "2022"]) await expect(stage(page).locator("svg text", { hasText: new RegExp(`^${year}$`) })).toHaveCount(1);

    // 4. Pointing at the seed opens its details: all four connections.
    await node(page, SEED).click();
    await expect(panel(page)).toContainText("Seed paper");
    await expect(panel(page).getByRole("heading", { level: 3 })).toHaveText(/^Connections\s*4$/);

    // 5. A connected paper: the verbatim evidence and the rule behind its link, and links out.
    await openNode(page, FOUNDATIONAL);
    await expect(panel(page)).toContainText("Connected, not in this workspace");
    await expect(panel(page)).toContainText("[1] A. Author et al. A paper about topic 1. Conf.");
    await expect(panel(page)).toContainText("The seed paper cites it.");
    await expect(panel(page).getByRole("link", { name: "Open paper" })).toHaveAttribute("href", /^\/papers\/pap_pw_trail_/);

    // 6. Relationship and review filters.
    await page.getByRole("button", { name: "Similar 1", exact: true }).click();
    await expect(node(page, SIMILAR)).toHaveCount(0);
    await expect(nodes(page)).toHaveCount(4);
    await page.getByRole("button", { name: "Similar 1", exact: true }).click();
    await expect(nodes(page)).toHaveCount(5);
    await page.getByRole("button", { name: "To review 4", exact: true }).click();
    await expect(page.getByText("No connections match these filters.")).toBeVisible();
    await expect(nodes(page)).toHaveCount(1);
    await page.getByRole("button", { name: "Clear filters" }).first().click();
    await expect(nodes(page)).toHaveCount(5);

    // 7. Search finds a paper and flies to it.
    await page.getByRole("combobox", { name: "Find a paper in the graph" }).fill("symbolic");
    await page.getByRole("option", { name: new RegExp(esc(COMPETING)) }).click();
    await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText(COMPETING);

    // 8. Focus on one paper's neighbourhood, then expand from the seed.
    await panel(page).getByRole("button", { name: "Focus on its connections" }).click();
    const showEverything = page.getByRole("button", { name: "Show everything" });
    await expect(showEverything).toBeVisible();
    await expect(nodes(page)).toHaveCount(2);
    await openNode(page, SEED);
    await panel(page).getByRole("button", { name: "Expand 3 more connections" }).click();
    await expect(nodes(page)).toHaveCount(5);
    await showEverything.click();
    await expect(showEverything).toHaveCount(0);

    // 9. Trace how two papers relate: through the seed.
    await openNode(page, FOUNDATIONAL);
    await panel(page).getByRole("button", { name: "Trace a path from here" }).click();
    await expect(page.getByText(/Choose a second paper to trace the path from/).first()).toBeVisible();
    await node(page, COMPETING).focus();
    await page.keyboard.press("Enter");
    const pathSummary = panel(page).getByRole("region", { name: "Path between two papers" });
    await expect(pathSummary).toContainText("Connected in 2 steps");
    await expect(pathSummary).toContainText(`cites ${FOUNDATIONAL}`);
    await pathSummary.getByRole("button", { name: "Clear the path" }).click();
    await expect(pathSummary).toHaveCount(0);

    // 10. Review from the graph: accept one, add one to the workspace, reject one.
    await openNode(page, FOUNDATIONAL);
    await panel(page).getByRole("button", { name: `Accept the connection to ${FOUNDATIONAL}` }).click();
    await expect(counts(page, "1 paper in the workspace · 4 connected · 4 connections · 3 to review")).toBeVisible();
    await openNode(page, SIMILAR);
    await panel(page).getByRole("button", { name: "Add to workspace" }).click();
    await expect(panel(page)).toContainText("In this workspace");
    await expect(counts(page, "2 papers in the workspace · 3 connected · 4 connections · 2 to review")).toBeVisible();
    await openNode(page, COMPETING);
    await panel(page).getByRole("button", { name: `Reject the connection to ${COMPETING}` }).click();
    await expect(node(page, COMPETING)).toHaveCount(0);
    await expect(page.getByText(/You can restore it from the trail's Rejected tab/)).toBeVisible();
    await expect(counts(page, "2 papers in the workspace · 2 connected · 3 connections · 1 to review")).toBeVisible();

    // 11. Zoom controls move the camera.
    const camera = stage(page).locator("svg > g[transform]").first();
    const before = await camera.getAttribute("transform");
    await page.getByRole("button", { name: "Zoom in" }).click();
    await expect.poll(() => camera.getAttribute("transform")).not.toBe(before);
    await page.getByRole("button", { name: "Fit the graph to the view" }).click();

    // 12. From a node to its place in the trail: the right tab, the evidence open.
    await openNode(page, EXTENSION);
    await panel(page).getByRole("link", { name: "Show in trail" }).click();
    await page.waitForURL(/\/trail\?edge=/);
    await expect(page.getByRole("article", { name: EXTENSION }).getByRole("button", { name: "Hide the evidence" })).toBeVisible();
    await expect(page.getByRole("button", { name: "To review 1", exact: true })).toHaveAttribute("aria-pressed", "true");
    // leaving the graph gave the background its full field back
    await expect(page.getByTestId("constellation")).toHaveAttribute("data-mode", "field");

    // 13. Everything persisted; the old graph URL forwards here.
    await page.goto(`/workspaces/${workspaceId}/graph`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/graph$`));
    await expect(counts(page, "2 papers in the workspace · 2 connected · 3 connections · 1 to review")).toBeVisible({ timeout: 10_000 });

    expect(consoleErrors).toEqual([]);
  });

  test("a workspace without connections says where they come from, reduced motion skips the entrance, and a failed load offers a retry", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Graph Empty Seed"]);
    await page.reload();
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

    await page.goto(`/workspace/${workspaceId}/graph`);
    // no entrance under reduced motion: straight to the settled graph
    await expect(stage(page)).toHaveAttribute("data-phase", "settled", { timeout: 10_000 });
    await expect(nodes(page)).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "No connections yet" })).toBeVisible();
    await expect(page.getByText("This workspace started from the seed paper alone.", { exact: false })).toBeVisible();
    await expect(page.getByRole("link", { name: "Discover related papers" })).toHaveAttribute("href", `/discover/${seedId}`);

    // The server failing is simulated for this one response; the page's handling is what's tested.
    await page.route(`**/api/v1/workspaces/${workspaceId}/graph`, (route) =>
      route.fulfill({ status: 500, json: { detail: { error: { code: "internal", message: "internal error" } } } }),
    );
    await page.reload();
    await expect(page.getByText("Could not load the research graph.")).toBeVisible({ timeout: 10_000 });
    await page.unroute(`**/api/v1/workspaces/${workspaceId}/graph`);
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(nodes(page)).toHaveCount(1, { timeout: 10_000 });
  });

  test("an unknown workspace gets an honest not-found state", async ({ page }) => {
    await page.goto("/workspace/ws_pw_graph_missing/graph");
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
  });
});
