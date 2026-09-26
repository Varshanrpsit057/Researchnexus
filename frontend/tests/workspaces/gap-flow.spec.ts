// spec: Phase 11 (Research Gaps) critical flow at /workspace/[id]/gaps.
//
// The gaps under test are the real pipeline's output: seed-gaps.py runs
// app/services/gaps/pipeline.py::build_gaps over the workspace's real
// papers -- profiling the discovered ones from their abstracts, applying
// the deterministic gap rules, and checking every statement against its
// passages -- exactly as the POST's background job does. Only the language
// model inside it is scripted (no BYOK key exists here). In the browser the
// only mocks are the `me` flag saying a key is saved, the LLM-gated POST,
// and its job's status, which carries the real run's own counts. Listing,
// accepting and rejecting gaps are the real backend.
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

const py = (args: string[]) => execFileSync(PYTHON, args).toString();

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
  await page.route("**/api/v1/me", async (route: Route) => {
    const res = await route.fetch();
    route.fulfill({ response: res, json: { ...(await res.json()), has_working_llm_key: true } });
  });
}

test.describe("Research gaps", () => {
  let seedId: string | null = null;

  test.afterEach(() => {
    if (seedId) {
      py([path.join(HELPERS, "cleanup-seeded-profile.py"), seedId]);
      py([TRAIL_FIXTURE, "restore", seedId]);
    }
    seedId = null;
  });

  test("a workspace's papers yield gaps traced to their passages, to accept or reject", async ({ page }) => {
    // 1. A real workspace: the uploaded seed plus three papers from a real discovery run.
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Gap Flow Seed"]);
    const stamp = Date.now();
    const runId = `run_pw_gaps_${stamp}`;
    py([TRAIL_FIXTURE, "seed", seedId, runId, `g${stamp}`]);
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_gd", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_gd" } } }),
    );
    await page.route("**/api/v1/jobs/job_pw_gd", (route) =>
      route.fulfill({ json: { job_id: "job_pw_gd", status: "succeeded", progress: { stage: "done" }, result_ref: runId, error: null } }),
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

    // 2. Workspace -> Gaps, from the overview's gaps station.
    await page.getByRole("link", { name: /^Gaps\s*:/ }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/gaps$`));
    await expect(page.getByRole("heading", { level: 1, name: "Research gaps" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "No gaps yet" })).toBeVisible({ timeout: 10_000 });
    // no key saved (real): a run can't start, and the page says which papers still need reading
    await expect(page.getByText("No working LLM provider key is saved, so a run can't start yet.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Find gaps" })).toBeDisabled();
    await expect(page.getByText(/1 of 4 papers has a research profile; the other 3 need a model to read their text first\./)).toBeVisible();

    // 3. A run: the first fails, the second is the real pipeline's.
    await claimAKey(page);
    const jobs: Record<string, { status: string; progress: Record<string, string>; error: string | null }> = {};
    let started = 0;
    await page.route(`**/api/v1/workspaces/${workspaceId}/gaps`, (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      started += 1;
      const jobId = `job_pw_gaps_${stamp}_${started}`;
      jobs[jobId] = { status: "running", progress: { gaps: "running" }, error: null };
      return route.fulfill({ status: 202, json: { job: { job_id: jobId, kind: "gaps", status: "queued", poll_url: `/api/v1/jobs/${jobId}` } } });
    });
    await page.route(`**/api/v1/jobs/job_pw_gaps_${stamp}_*`, (route) => {
      const jobId = new URL(route.request().url()).pathname.split("/").pop()!;
      route.fulfill({ json: { job_id: jobId, kind: "gaps", workspace_id: workspaceId, result_ref: null, ...jobs[jobId] } });
    });
    await page.reload();
    await page.getByRole("button", { name: "Find gaps" }).click();
    await expect(page.getByText(/Profiling papers where needed, applying the gap rules/)).toBeVisible();
    jobs[`job_pw_gaps_${stamp}_1`] = { status: "failed", progress: { gaps: "running" }, error: "synthesis_internal_ref_77" };
    await expect(page.getByText("The run failed before it finished. Try again.")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("synthesis_internal_ref_77")).toBeHidden();
    await page.getByText("Technical details").click();
    await expect(page.getByText("synthesis_internal_ref_77")).toBeVisible();

    await page.getByRole("button", { name: "Find gaps" }).click();
    await expect(page.getByText(/Profiling papers where needed/)).toBeVisible();
    const real = JSON.parse(py([path.join(HELPERS, "seed-gaps.py"), workspaceId])) as {
      progress: Record<string, string>;
      gaps: { gap_id: string; statement: string; supporting_papers: string[] }[];
    };
    jobs[`job_pw_gaps_${stamp}_2`] = { status: "succeeded", progress: real.progress, error: null };
    const kept = Number(real.progress.count);
    expect(kept).toBeGreaterThan(1);
    await expect(page.getByText(`Kept ${kept} of ${real.progress.candidates} candidate gaps.`)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/1 wasn't supported by its own evidence/)).toBeVisible();
    await expect(page.getByText(`Read ${real.progress.profiled} papers to build a research profile first.`)).toBeVisible();
    const list = page.getByRole("list", { name: `To review: ${kept} gaps` });
    await expect(list.getByRole("button")).toHaveCount(kept);
    await expect(page.getByText(new RegExp(`^${kept} gaps across \\d papers: ${kept} to review, 0 accepted, 0 rejected\\.`))).toBeVisible();

    // 4. A gap, traced to the passages it rests on.
    const metricGap = real.gaps.find((g) => g.statement === METRIC_GAP)!;
    expect(metricGap).toBeTruthy();
    await list.getByRole("button", { name: /share no common metric/ }).click();
    const detail = page.getByTestId("gap-detail");
    await expect(detail.getByRole("heading", { level: 2, name: METRIC_GAP })).toBeVisible();
    await expect(detail).toContainText("Evaluation gap · The papers report metrics, and no two of them share one.");
    await expect(detail).toContainText("Medium confidence");
    await expect(detail).toContainText("1 of 2 papers backed by full text; the rest by abstracts");
    await expect(detail).toContainText("States it · Abstract");
    await expect(detail.getByText("“improves factual grounding”")).toBeVisible();
    await expect(detail.getByText("“F1”")).toBeVisible();
    const similarId = metricGap.supporting_papers.find((p) => p !== seedId)!;
    await expect(detail.getByRole("link", { name: SIMILAR })).toHaveAttribute("href", `/papers/${similarId}`);
    await expect(detail.getByRole("link", { name: "Show in graph" }).last()).toHaveAttribute(
      "href",
      `/workspace/${workspaceId}/graph?paper=${similarId}`,
    );

    // 5. Accept it; the decision is saved (a reload keeps it, deep-linked).
    await detail.getByRole("button", { name: "Accept gap" }).click();
    await expect(detail.getByRole("button", { name: "Move back to review" })).toBeVisible();
    await expect(detail.getByRole("link", { name: "Propose directions" })).toHaveAttribute("href", `/workspace/${workspaceId}/directions?gap=${metricGap.gap_id}`);
    await expect(page).toHaveURL(new RegExp(`/workspace/${workspaceId}/gaps\\?gap=${metricGap.gap_id}$`));
    await page.reload();
    await expect(detail.getByRole("heading", { level: 2, name: METRIC_GAP })).toBeVisible({ timeout: 10_000 });
    await expect(detail.getByRole("button", { name: "Move back to review" })).toBeVisible();

    // 6. The next one, rejected.
    await detail.getByRole("button", { name: "Next to review" }).click();
    await expect(detail.getByRole("button", { name: "Reject" })).toBeVisible();
    const rejected = await detail.getByRole("heading", { level: 2 }).textContent();
    await detail.getByRole("button", { name: "Reject" }).click();
    await expect(detail.getByRole("button", { name: "Move back to review" })).toBeVisible();

    // 7. Filters and search (phones close the gap's sheet first).
    if (test.info().project.name !== "chromium") {
      await page.getByRole("button", { name: "All gaps" }).click();
      await expect(detail).toHaveCount(0);
    }
    await expect(page.getByRole("button", { name: /^To review\s*\d+$/ })).toHaveText(new RegExp(`${kept - 2}$`));
    await page.getByRole("button", { name: /^Rejected\s*1$/ }).click();
    await expect(page.getByRole("list", { name: "Rejected: 1 gap" }).getByRole("button", { name: new RegExp(rejected!.slice(0, 40).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) })).toBeVisible();
    await page.getByRole("button", { name: /^All\s*\d+$/ }).click();
    await page.getByRole("searchbox", { name: "Search the gaps" }).fill("symbolic reasoning");
    await expect(page.getByRole("list", { name: "All gaps: 1 gap" }).getByRole("button")).toHaveCount(1);
    await page.getByRole("searchbox", { name: "Search the gaps" }).fill("no such thing anywhere");
    await expect(page.getByRole("heading", { name: "No gaps match" })).toBeVisible();
    await page.getByRole("button", { name: "Clear the filters" }).click();
    await expect(page.getByRole("list", { name: `All gaps: ${kept} gaps` })).toBeVisible();

    // 8. The overview links a decision straight to its gap; the old URL still lands here.
    await page.goto(`/workspace/${workspaceId}`);
    await expect(page.getByRole("link", { name: new RegExp(`Accepted gap.*${METRIC_GAP.slice(0, 30)}`) })).toHaveAttribute(
      "href",
      `/workspace/${workspaceId}/gaps?gap=${metricGap.gap_id}`,
    );
    await page.goto(`/workspaces/${workspaceId}/gaps`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/gaps$`));

    expect(consoleErrors).toEqual([]);
  });

  test("a workspace with only its seed explains what gaps need, and a failed load offers a retry", async ({ page }) => {
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Gap Empty Seed"]);
    await page.reload();
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];
    const consoleErrors = collectConsoleErrors(page);
    await page.goto(`/workspace/${workspaceId}/gaps`);
    await expect(page.getByRole("heading", { name: "Gaps need two papers" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: "Add papers" })).toHaveAttribute("href", `/workspace/${workspaceId}#papers`);
    await expect(page.getByRole("link", { name: "Discover related papers" })).toHaveAttribute("href", `/discover/${seedId}`);

    // The server failing is simulated for this one response; the page's handling is what's tested.
    await page.route(`**/api/v1/workspaces/${workspaceId}/gaps`, (route) =>
      route.fulfill({ status: 500, json: { detail: { error: { code: "internal", message: "internal error" } } } }),
    );
    await page.reload();
    await expect(page.getByText("Could not load this workspace's gaps.")).toBeVisible({ timeout: 10_000 });
    await page.unroute(`**/api/v1/workspaces/${workspaceId}/gaps`);
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("heading", { name: "Gaps need two papers" })).toBeVisible({ timeout: 10_000 });
    expect(consoleErrors).toEqual([]);
  });

  test("a missing workspace says so", async ({ page }) => {
    await page.goto("/workspace/ws_pw_gaps_missing/gaps");
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
  });
});
