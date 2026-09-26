// spec: Phase 13 (Citations) critical flow at /workspace/[id]/citations.
//
// Nothing here is mocked: the ledger is the real GET .../citations over a
// real workspace (the uploaded seed plus three papers from a real discovery
// run), and every citation it lists comes from state the real pipelines
// stored -- a comparison (seed-comparison.py), gaps (seed-gaps.py) and an
// answered chat turn (seed-chat-turn.py), each with its model scripted
// because no BYOK key exists here, never its evidence.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPERS = __dirname;
const TRAIL_FIXTURE = path.join(__dirname, "..", "trail", "seed-trail-run.py");

const SIMILAR = "Phase 7 Fixture: Retrieval-Augmented Generators Revisited";
const COMPETING = "Phase 7 Fixture: A Competing Symbolic Approach";
const EXTENDING = "Phase 7 Fixture: Extending Parametric Memory with Dense Retrievers";
const SEED_TITLE = /ResearchNexus: A Synthetic Test Paper/;

const py = (args: string[]) => execFileSync(PYTHON, args).toString();
const phone = () => test.info().project.name !== "chromium";

async function uploadSeed(page: Page): Promise<string> {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Browse for a file" }).click();
  await (await chooser).setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
  await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
  return page.url().split("/papers/")[1].split("?")[0];
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    // intentional failures: the simulated 500 and the missing workspace's real 404
    if (m.type() === "error" && !/\b(500|404)\b/.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test.describe("Citations", () => {
  let seedId: string | null = null;

  test.afterEach(() => {
    if (seedId) {
      py([path.join(HELPERS, "cleanup-seeded-profile.py"), seedId]);
      py([TRAIL_FIXTURE, "restore", seedId]);
    }
    seedId = null;
  });

  test("every paper's reference and every place the workspace cites it, with the passage", async ({ page }) => {
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    // 1. A real workspace: the seed plus three papers from a real discovery run.
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Citation Flow Seed"]);
    const stamp = Date.now();
    const runId = `run_pw_cites_${stamp}`;
    py([TRAIL_FIXTURE, "seed", seedId, runId, `t${stamp}`]);
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_ct", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_ct" } } }),
    );
    await page.route("**/api/v1/jobs/job_pw_ct", (route) =>
      route.fulfill({ json: { job_id: "job_pw_ct", status: "succeeded", progress: { stage: "done" }, result_ref: runId, error: null } }),
    );
    const consoleErrors = collectConsoleErrors(page);
    await page.goto(`/discover/${seedId}`);
    await expect(page.getByText(SIMILAR)).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Create workspace", exact: true }).click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 15_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];
    await page.getByRole("button", { name: "Add papers" }).click();
    for (const title of [SIMILAR, COMPETING, EXTENDING]) await page.getByRole("checkbox", { name: new RegExp(title) }).check();
    await page.getByRole("button", { name: "Add 3 papers" }).click();
    await expect(page.getByRole("heading", { name: /^Papers\s*4$/ })).toBeVisible({ timeout: 15_000 });

    // 2. Workspace -> Citations. Before anything cites them: the papers, and the seed's own bibliography.
    await page.getByRole("link", { name: /^Citations/ }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/citations$`));
    await expect(page.getByRole("heading", { level: 1, name: "Citations" })).toBeVisible();
    await expect(page.getByText(/^4 papers, none cited in the workspace yet\. The seed paper lists 5 references; the trail matched 1 to a paper\./)).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Nothing in the workspace cites these papers yet.", { exact: false })).toBeVisible();

    // 3. The workspace cites them, through the real pipelines.
    py([path.join(HELPERS, "seed-comparison.py"), workspaceId]);
    py([path.join(HELPERS, "seed-gaps.py"), workspaceId]);
    const turn = JSON.parse(py([path.join(HELPERS, "seed-chat-turn.py"), "answer", workspaceId, `c${stamp}`])) as {
      session_id: string;
      claims: { sentence: string; paper_id: string }[];
    };
    await page.reload();
    await expect(page.getByText(/^4 papers, cited \d+ times in this workspace: \d+ in chat, \d+ in comparison, \d+ in gaps\./)).toBeVisible({ timeout: 10_000 });
    const list = page.getByRole("list", { name: /^Papers: \d+$/ });

    // 4. A paper's dossier: its reference, and where it is cited with the passage.
    await list.getByRole("button", { name: new RegExp(SIMILAR) }).click();
    const detail = page.getByTestId("citation-detail");
    await expect(detail.getByRole("heading", { level: 2, name: SIMILAR })).toBeVisible();
    await expect(detail).toContainText("T. Fixture");
    await expect(detail).toContainText("Built from its title, authors and year; formatted by rule, never generated.");
    await expect(detail.getByText(/^Fixture, T\. \(2021\)\. Phase 7 Fixture: Retrieval-Augmented Generators Revisited\./)).toBeVisible();
    await expect(detail).toContainText("Method: Generators that read retrieved passages");
    await expect(detail.getByText("“We revisit generators that read retrieved passages”").first()).toBeVisible();
    await expect(detail.getByRole("link", { name: "Open the comparison" }).first()).toHaveAttribute("href", `/workspace/${workspaceId}/compare`);
    await expect(detail.getByRole("link", { name: "Open the gap" }).first()).toHaveAttribute("href", new RegExp(`^/workspace/${workspaceId}/gaps\\?gap=gap_`));
    await expect(detail.getByRole("link", { name: "Show in graph" })).toHaveAttribute("href", new RegExp(`/graph\\?paper=`));

    // the reference in every style; one copies, all copy, a .bib downloads
    await detail.getByRole("button", { name: "IEEE", exact: true }).click();
    await expect(detail.getByText(/^\[\d\] T\. Fixture, /)).toBeVisible();
    await detail.getByRole("button", { name: "BibTeX", exact: true }).click();
    await expect(detail.locator("pre")).toContainText("@");
    await detail.getByRole("button", { name: "Copy BibTeX reference" }).click();
    await expect(detail.getByRole("button", { name: "Copy BibTeX reference" })).toContainText("Copied");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^@\w+\{/);
    if (phone()) await page.getByRole("button", { name: "All papers", exact: true }).click();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download .bib" }).click();
    expect((await download).suggestedFilename()).toMatch(/\.bib$/);
    await page.getByRole("button", { name: "Copy all as BibTeX" }).click();
    expect((await page.evaluate(() => navigator.clipboard.readText())).match(/^@/gm)?.length).toBe(4);

    // 5. The chat answer's citation leads back to its thread.
    await list.getByRole("button", { name: SEED_TITLE }).click();
    await expect(detail).toContainText("An answer in chat cites it");
    await expect(detail).toContainText(turn.claims[0].sentence);
    await expect(detail.getByRole("link", { name: "Open the chat" }).first()).toHaveAttribute("href", `/workspace/${workspaceId}/chat?session=${turn.session_id}`);
    // the seed's own references, matched to the papers the trail resolved
    await expect(detail).toContainText("5 listed; the trail matched 1 to a paper");
    await expect(detail.getByRole("link", { name: "Open the paper" })).toHaveAttribute("href", /\/papers\/pap_pw_trail_/);
    if (phone()) await page.getByRole("button", { name: "All papers", exact: true }).click();

    // 6. What discovery knows: the extension cites the seed, and its trail edge links there.
    await list.getByRole("button", { name: new RegExp(EXTENDING) }).click();
    await expect(detail).toContainText("It cites the seed paper");
    await expect(detail.getByRole("link", { name: "In the trail" }).first()).toHaveAttribute("href", new RegExp(`/workspace/${workspaceId}/trail\\?edge=`));
    if (phone()) await page.getByRole("button", { name: "All papers", exact: true }).click();

    // 7. Filter, search and sort.
    await page.getByRole("button", { name: /^In chat\s*1$/ }).click();
    await expect(list.getByRole("button")).toHaveCount(1);
    await page.getByRole("button", { name: /^All papers\s*4$/ }).click();
    await page.getByRole("searchbox", { name: "Search the citations" }).fill("revisit generators");
    await expect(list.getByRole("button")).toHaveCount(1);
    await expect(list.getByRole("button").first()).toContainText(SIMILAR);
    await page.getByRole("searchbox", { name: "Search the citations" }).fill("");
    await page.getByLabel("Sort").selectOption("oldest");
    await expect(list.getByRole("button").first()).toContainText(/2021/);

    // 8. The old URL still lands here.
    await page.goto(`/workspaces/${workspaceId}/citations`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/citations$`));
    expect(consoleErrors).toEqual([]);
  });

  test("a workspace nothing cites yet says how to change that, and a failed load offers a retry", async ({ page }) => {
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Citation Empty Seed"]);
    await page.reload();
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];
    const consoleErrors = collectConsoleErrors(page);
    await page.goto(`/workspace/${workspaceId}/citations`);
    await expect(page.getByText(/^1 paper, none cited in the workspace yet\./)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Nothing in the workspace cites these papers yet.", { exact: false })).toBeVisible();

    // The server failing is simulated for this one response; the page's handling is what's tested.
    await page.route(`**/api/v1/workspaces/${workspaceId}/citations`, (route) =>
      route.fulfill({ status: 500, json: { detail: { error: { code: "internal", message: "internal error" } } } }),
    );
    await page.reload();
    await expect(page.getByText("Could not load this workspace's citations.")).toBeVisible({ timeout: 10_000 });
    await page.unroute(`**/api/v1/workspaces/${workspaceId}/citations`);
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText(/^1 paper, none cited in the workspace yet\./)).toBeVisible({ timeout: 10_000 });
    expect(consoleErrors).toEqual([]);
  });

  test("a missing workspace says so", async ({ page }) => {
    await page.goto("/workspace/ws_pw_cites_missing/citations");
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
  });
});
