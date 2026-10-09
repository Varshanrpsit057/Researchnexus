// spec: Phase 12 (Research Directions) critical flow at /workspace/[id]/directions.
//
// Everything a direction rests on is real: the workspace's papers, the gaps
// the real gap pipeline finds in them (seed-gaps.py), and the reader's own
// decisions to accept two of those gaps on the Gaps page. Proposing
// directions is LLM-gated and no BYOK key exists here, so the POST is
// answered by seed-directions.py, which runs the real direction pipeline
// (grounding check, critique, confidence band, persistence) over exactly the
// gaps the page sent, with only the model scripted. Listing directions and
// accepting or rejecting them is the real backend.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page, Route } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPERS = __dirname;
const TRAIL_FIXTURE = path.join(__dirname, "..", "trail", "seed-trail-run.py");

const SIMILAR = "Phase 7 Fixture: Retrieval-Augmented Generators Revisited";
const COMPETING = "Phase 7 Fixture: A Competing Symbolic Approach";
const EXTENDING = "Phase 7 Fixture: Extending Parametric Memory with Dense Retrievers";
const METRIC_GAP = "The 2 papers share no common metric, so their results are not directly comparable.";
const METHOD_GAP = "None of the 2 papers that share a research problem with the paper using dense retrieval with reranking applies it.";
const HYPOTHESIS = "Pair dense retrieval with reranking with claim-level verification on the problem the papers share.";

const py = (args: string[]) => execFileSync(PYTHON, args).toString();
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

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

async function claimAKey(page: Page) {
  await page.route("**/api/v1/auth/session", async (route: Route) => {
    const res = await route.fetch();
    const body = await res.json();
    route.fulfill({ response: res, json: { user: { ...body.user, has_working_llm_key: true } } });
  });
}

const phone = () => test.info().project.name !== "chromium";

test.describe("Research directions", () => {
  let seedId: string | null = null;

  test.afterEach(() => {
    if (seedId) {
      py([path.join(HELPERS, "cleanup-seeded-profile.py"), seedId]);
      py([TRAIL_FIXTURE, "restore", seedId]);
    }
    seedId = null;
  });

  test("accepted gaps become directions traced to their evidence, to accept or reject", async ({ page }) => {
    // 1. A real workspace and the gaps the real pipeline finds in it.
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Direction Flow Seed"]);
    const stamp = Date.now();
    const runId = `run_pw_dirs_${stamp}`;
    py([TRAIL_FIXTURE, "seed", seedId, runId, `d${stamp}`]);
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_dd", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_dd" } } }),
    );
    await page.route("**/api/v1/jobs/job_pw_dd", (route) =>
      route.fulfill({ json: { job_id: "job_pw_dd", status: "succeeded", progress: { stage: "done" }, result_ref: runId, error: null } }),
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
    const gaps = JSON.parse(py([path.join(HELPERS, "seed-gaps.py"), workspaceId])).gaps as { gap_id: string; statement: string }[];
    const metricGap = gaps.find((g) => g.statement === METRIC_GAP)!;
    const methodGap = gaps.find((g) => g.statement === METHOD_GAP)!;
    expect(metricGap && methodGap).toBeTruthy();

    // 2. Before any gap is accepted, the page says where directions come from.
    await page.goto(`/workspace/${workspaceId}/directions`);
    await expect(page.getByRole("heading", { level: 1, name: "Research directions" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Directions start from gaps you accept" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: new RegExp(`^Review ${gaps.length} gaps$`) })).toHaveAttribute("href", `/workspace/${workspaceId}/gaps`);

    // 3. The reader accepts two real gaps on the Gaps page, then follows one to its directions.
    await page.goto(`/workspace/${workspaceId}/gaps`);
    const gapDetail = page.getByTestId("gap-detail");
    for (const statement of [METRIC_GAP, METHOD_GAP]) {
      await page.getByRole("list", { name: /^To review:/ }).getByRole("button", { name: new RegExp(escape(statement)) }).click();
      await expect(gapDetail.getByRole("heading", { level: 2, name: statement })).toBeVisible();
      await gapDetail.getByRole("button", { name: "Accept gap" }).click();
      await expect(gapDetail.getByRole("button", { name: "Move back to review" })).toBeVisible();
      if (phone() && statement === METRIC_GAP) await page.getByRole("button", { name: "All gaps" }).click();
    }
    await gapDetail.getByRole("link", { name: "Propose directions" }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/directions\\?gap=${methodGap.gap_id}$`));
    await expect(page.getByRole("heading", { name: "No directions yet" })).toBeVisible({ timeout: 10_000 });
    const starts = page.getByRole("list", { name: "Accepted gaps to propose from" }).getByRole("button");
    await expect(starts).toHaveCount(2);
    await expect(starts.filter({ hasText: METHOD_GAP })).toHaveAttribute("aria-pressed", "true"); // the gap it came from
    await expect(starts.filter({ hasText: METRIC_GAP })).toHaveAttribute("aria-pressed", "false");
    // no key saved (real): proposing is off and says why
    await expect(page.getByText("No working LLM provider key is saved, so directions can't be proposed yet.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Propose directions from 1 gap" })).toBeDisabled();

    // 4. Propose from both: the real pipeline over exactly the gaps the page sent.
    await claimAKey(page);
    const sent: string[][] = [];
    await page.route(`**/api/v1/workspaces/${workspaceId}/directions`, async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const gapIds = (route.request().postDataJSON() as { gap_ids: string[] }).gap_ids;
      sent.push(gapIds);
      return route.fulfill({ json: JSON.parse(py([path.join(HELPERS, "seed-directions.py"), workspaceId, ...gapIds])) });
    });
    await page.reload();
    await starts.filter({ hasText: METRIC_GAP }).click();
    await page.getByRole("button", { name: "Propose directions from 2 gaps" }).click();
    const outcome = page.getByRole("status").filter({ hasText: "Proposed 3 directions from 2 gaps." });
    await expect(outcome).toBeVisible({ timeout: 20_000 });
    await expect(outcome).toContainText("1 proposal was dropped for naming something the gap's evidence doesn't contain.");
    expect(new Set(sent[0])).toEqual(new Set([metricGap.gap_id, methodGap.gap_id]));
    await expect(page.getByText(/^3 directions from 2 gaps: 3 to review, 0 accepted, 0 rejected\./)).toBeVisible();

    // 5. A direction: its plan, how it was judged, and the passages it inherits from its gap.
    await page.getByRole("button", { name: new RegExp(escape(HYPOTHESIS)) }).click();
    const detail = page.getByTestId("direction-detail");
    await expect(detail.getByRole("heading", { level: 2, name: HYPOTHESIS })).toBeVisible();
    await expect(detail).toContainText("Model hypothesis");
    await expect(detail).toContainText("Methodclaim-level verification");
    await expect(detail.getByRole("img", { name: "Grounded: 3 of 5" })).toBeVisible();
    await expect(detail.getByRole("img", { name: "Feasible: 2 of 5" })).toBeVisible();
    await expect(detail).toContainText("Medium confidence");
    await expect(detail.getByRole("link", { name: METHOD_GAP })).toHaveAttribute("href", `/workspace/${workspaceId}/gaps?gap=${methodGap.gap_id}`);
    await expect(detail.getByText("“hallucination in knowledge intensive tasks”")).toBeVisible();
    await expect(detail.getByRole("link", { name: "Show in graph" }).first()).toHaveAttribute("href", new RegExp(`^/workspace/${workspaceId}/graph\\?paper=`));
    await expect(detail.getByRole("link", { name: "Open its gap" })).toHaveAttribute("href", `/workspace/${workspaceId}/gaps?gap=${methodGap.gap_id}`);

    // 6. Accept it; the decision is saved (a reload keeps it, deep-linked). Reject the next.
    await detail.getByRole("button", { name: "Accept direction" }).click();
    await expect(detail.getByRole("button", { name: "Move back to review" })).toBeVisible();
    await expect(page).toHaveURL(/\/directions\?direction=dir_/);
    await page.reload();
    await expect(detail.getByRole("heading", { level: 2, name: HYPOTHESIS })).toBeVisible({ timeout: 10_000 });
    await expect(detail.getByRole("button", { name: "Move back to review" })).toBeVisible();
    await detail.getByRole("button", { name: "Next to review" }).click();
    await detail.getByRole("button", { name: "Reject" }).click();
    await expect(detail.getByRole("button", { name: "Move back to review" })).toBeVisible();

    // 7. Filters (phones close the direction's sheet first).
    if (phone()) {
      await page.getByRole("button", { name: "All directions" }).click();
      await expect(detail).toHaveCount(0);
    }
    await expect(page.getByRole("button", { name: /^To review\s*1$/ })).toBeVisible();
    await page.getByRole("button", { name: /^All\s*3$/ }).click();
    await page.getByRole("button", { name: "Hypotheses" }).click();
    await expect(page.getByRole("region", { name: "All directions: 1" })).toBeVisible();
    await page.getByRole("button", { name: "Every kind" }).click();
    await page.getByRole("searchbox", { name: "Search the directions" }).fill("shared metric");
    await expect(page.getByRole("region", { name: "All directions: 1" })).toContainText(METRIC_GAP);
    await page.getByRole("searchbox", { name: "Search the directions" }).fill("");

    // 8. The overview links an accepted direction straight to it; the old URL still lands here.
    await page.goto(`/workspace/${workspaceId}`);
    await expect(page.getByRole("link", { name: new RegExp(`Accepted direction.*${escape(HYPOTHESIS.slice(0, 30))}`) })).toHaveAttribute(
      "href",
      /\/directions\?direction=dir_/,
    );
    await page.goto(`/workspaces/${workspaceId}/directions`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/directions$`));

    expect(consoleErrors).toEqual([]);
  });

  test("a failed load offers a retry", async ({ page }) => {
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Direction Empty Seed"]);
    await page.reload();
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];
    const consoleErrors = collectConsoleErrors(page);
    await page.goto(`/workspace/${workspaceId}/directions`);
    await expect(page.getByRole("heading", { name: "Directions start from gaps you accept" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: "Find gaps" })).toHaveAttribute("href", `/workspace/${workspaceId}/gaps`);

    // The server failing is simulated for this one response; the page's handling is what's tested.
    await page.route(`**/api/v1/workspaces/${workspaceId}/directions`, (route) =>
      route.fulfill({ status: 500, json: { detail: { error: { code: "internal", message: "internal error" } } } }),
    );
    await page.reload();
    await expect(page.getByText("Could not load this workspace's directions.")).toBeVisible({ timeout: 10_000 });
    await page.unroute(`**/api/v1/workspaces/${workspaceId}/directions`);
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("heading", { name: "Directions start from gaps you accept" })).toBeVisible({ timeout: 10_000 });
    expect(consoleErrors).toEqual([]);
  });

  test("a missing workspace says so", async ({ page }) => {
    await page.goto("/workspace/ws_pw_dirs_missing/directions");
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
  });
});
