// spec: Slice 6 (Compare -> Gap) critical flow.
//
// Both `compare` and `gaps` generation are LLM-gated, and the real backend
// 409s `llm_key_required` synchronously for each -- before any synthesis
// or job work starts (see routers/synthesis.py) -- since no working BYOK
// key exists in this environment. Both POSTs are mocked at the network
// layer for that reason. Everything else runs for real: auth, upload,
// workspace creation, and adding a second paper by id (compare requires
// >=2 workspace members); the initial `GET .../gaps` list is also real,
// since listing needs no LLM key and a fresh workspace genuinely has zero
// gaps -- proving the empty state without a mock.
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

async function createWorkspaceWithTwoPapers(
  page: import("@playwright/test").Page,
  label: string
): Promise<{ workspaceId: string; seedPaperId: string; secondPaperId: string }> {
  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Browse for a file" }).click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
  await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
  const seedPaperId = page.url().split("/papers/")[1].split("?")[0];
  seedProfile(seedPaperId, label);
  await page.reload();
  await page.getByText("Skip discovery, start a workspace with just this paper").click();
  await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
  await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
  const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

  const secondPaperId = `pap_pw_gap_${Date.now()}`;
  seedSecondPaperAndEdge(seedPaperId, secondPaperId, workspaceId);
  await page.goto(`/workspaces/${workspaceId}/papers`);
  await page.getByLabel("Add a paper by ID").fill(secondPaperId);
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText(secondPaperId)).toBeVisible({ timeout: 5_000 });

  return { workspaceId, seedPaperId, secondPaperId };
}

const NOT_FOUND_COMPARISON = { detail: { error: { code: "not_found", message: "no comparison run yet" } } };

test.describe("Compare -> Gap", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) cleanupSeededProfile(seededPaperId);
    seededPaperId = null;
  });

  test("comparing papers renders a coverage table, and a persisted result reappears on revisit", async ({ page }) => {
    const { workspaceId, seedPaperId, secondPaperId } = await createWorkspaceWithTwoPapers(page, "Compare Flow Seed Paper");
    seededPaperId = seedPaperId;

    const comparisonResponse = {
      comparison_id: "cmp_pw_1",
      schema: ["method", "dataset"],
      generated_by: "playwright-mock",
      paper_ids: [seedPaperId, secondPaperId],
      rows: [
        {
          paper_id: seedPaperId,
          cells: {
            method: { column: "method", text: "Retrieval-augmented generation", span: null, claim_id: null, grounding: "full_text", conflicting: [] },
            dataset: { column: "dataset", text: "Natural Questions", span: null, claim_id: null, grounding: "full_text", conflicting: [] },
          },
        },
        {
          paper_id: secondPaperId,
          cells: {
            method: { column: "method", text: "Dense retrieval", span: null, claim_id: null, grounding: "full_text", conflicting: ["claim_x"] },
            dataset: { column: "dataset", text: null, span: null, claim_id: null, grounding: "full_text", conflicting: [] },
          },
        },
      ],
      coverage: 0.85,
      decontext_eval: 0.7,
      warnings: [] as string[],
    };

    // A real comparison was never actually run (the POST below is mocked,
    // so nothing lands in the backend's own `comparisons` table) -- this
    // flag stands in for "does one exist yet" across the GET mock so the
    // same test can prove both the pre-run empty state and the post-run
    // persisted-on-reload render, mirroring discover-flow.spec.ts's
    // mutable-flag approach for the same reason (a mock can't persist).
    let hasComparison = false;
    await page.route(`**/api/v1/workspaces/${workspaceId}/compare`, (route) => {
      if (route.request().method() === "POST") {
        hasComparison = true;
        route.fulfill({ json: comparisonResponse });
      } else {
        route.fulfill(hasComparison ? { json: comparisonResponse } : { status: 404, json: NOT_FOUND_COMPARISON });
      }
    });

    await page.goto(`/workspaces/${workspaceId}/compare`);
    await expect(page.getByText("No comparison yet")).toBeVisible({ timeout: 5_000 });

    await page.locator("label", { hasText: seedPaperId }).click();
    await page.locator("label", { hasText: secondPaperId }).click();
    await page.getByRole("button", { name: /Compare 2 papers/ }).click();

    await expect(page.getByText("85% coverage")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("70% decontextualised")).toBeVisible();
    // Scoped to the table: the mocked cell text collides (case-
    // insensitively, Playwright's default) with the real seed paper's own
    // title, which the workspace chrome also renders on this page.
    const table = page.locator("table");
    await expect(table.getByText("Retrieval-augmented generation")).toBeVisible();
    await expect(table.getByText("Dense retrieval")).toBeVisible();
    await expect(table.getByText("conflicts with 1")).toBeVisible();

    // The real regression: before this session's Slice 6 pass, `result`
    // was local-only `useState`, so a reload always re-showed "No
    // comparison yet" even though a real comparison was on record.
    await page.reload();
    await expect(page.getByText("85% coverage")).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("table").getByText("Retrieval-augmented generation")).toBeVisible();
  });

  test("generating gaps renders an evidence-backed card you can accept, and a failed run shows a clean retryable message", async ({ page }) => {
    const { workspaceId, seedPaperId, secondPaperId } = await createWorkspaceWithTwoPapers(page, "Gap Flow Seed Paper");
    seededPaperId = seedPaperId;

    await page.goto(`/workspaces/${workspaceId}/gaps`);
    // Real, unmocked GET: a fresh workspace has genuinely generated no
    // gaps yet, so this proves the empty state without a mock.
    await expect(page.getByText("No candidate gaps")).toBeVisible({ timeout: 5_000 });

    // 1. A failed run first: clean primary message, raw detail demoted --
    // the same treatment discover-flow.spec.ts already proved for
    // discovery, now covering the identical gap in Gaps' own job-failure
    // handling (the frontend previously had no failed-job branch at all).
    await page.route(`**/api/v1/workspaces/${workspaceId}/gaps*`, (route) => {
      if (route.request().method() === "POST") {
        route.fulfill({ json: { job: { job_id: "job_pw_gap_1", kind: "gaps", status: "queued", poll_url: "/api/v1/jobs/job_pw_gap_1" } } });
      } else {
        route.continue();
      }
    });
    let job1Status: "running" | "failed" = "running";
    await page.route("**/api/v1/jobs/job_pw_gap_1", (route) => {
      const body =
        job1Status === "running"
          ? { job_id: "job_pw_gap_1", status: "running", progress: { gaps: "running" }, result_ref: null, error: null }
          : { job_id: "job_pw_gap_1", status: "failed", progress: { gaps: "running" }, result_ref: null, error: "synthesis_internal_ref_77" };
      route.fulfill({ json: body });
    });
    await page.getByRole("button", { name: "Generate gaps" }).click();
    await expect(page.getByText("Generating gaps from this workspace's papers")).toBeVisible();
    job1Status = "failed";
    await expect(page.getByText("Gap generation failed. Try again.")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("synthesis_internal_ref_77")).not.toBeVisible();
    await page.getByText("Technical details").click();
    await expect(page.getByText("synthesis_internal_ref_77")).toBeVisible();

    // 2. Retry with a fresh job id (real backend behavior: `new_id` never
    // repeats), this time succeeding, to verify the gap card's render and
    // the accept transition.
    const mockedGap = {
      gap_id: "gap_pw_1",
      workspace_id: workspaceId,
      statement: "No compared method reports results under low-resource training data.",
      gap_type: "EVALUATION_GAP",
      supporting_papers: [seedPaperId, secondPaperId],
      supporting_evidence: [
        { paper_id: seedPaperId, role: "target_claim", span: { paper_id: seedPaperId, section: "Limitations", page: 8, char_start: null, char_end: null, quote: "we did not evaluate under low-resource conditions" } },
      ],
      conflicting_evidence: [] as unknown[],
      why_unaddressed: "Both papers evaluate only on full-scale training sets.",
      affected_methods: ["retrieval-augmented generation"],
      affected_datasets: ["Natural Questions"],
      evidence_coverage: 0.6,
      novelty_assessment: "Moderate -- adjacent work exists but not for this method pairing.",
      confidence: "medium",
      confidence_basis: { agreement: "2 of 2 papers support this reading" },
      proposed_direction: "Evaluate the compared methods under a low-resource training regime.",
      detection_rule: "evaluation_axis_missing",
      self_support_passed: true,
      user_state: "candidate",
      generated_at: "2026-01-01T00:00:00Z",
      generator_model: "playwright-mock",
    };
    let gapState: "candidate" | "accepted" = "candidate";
    await page.unroute(`**/api/v1/workspaces/${workspaceId}/gaps*`);
    await page.route(`**/api/v1/workspaces/${workspaceId}/gaps*`, (route) => {
      if (route.request().method() === "POST") {
        route.fulfill({ json: { job: { job_id: "job_pw_gap_2", kind: "gaps", status: "queued", poll_url: "/api/v1/jobs/job_pw_gap_2" } } });
      } else {
        const url = new URL(route.request().url());
        const state = url.searchParams.get("state") ?? "candidate";
        const gaps = state === gapState ? [{ ...mockedGap, user_state: gapState }] : [];
        route.fulfill({ json: { gaps } });
      }
    });
    let job2Status: "running" | "succeeded" = "running";
    await page.route("**/api/v1/jobs/job_pw_gap_2", (route) => {
      const body =
        job2Status === "running"
          ? { job_id: "job_pw_gap_2", status: "running", progress: { gaps: "running" }, result_ref: null, error: null }
          : { job_id: "job_pw_gap_2", status: "succeeded", progress: { gaps: "done", count: "1" }, result_ref: workspaceId, error: null };
      route.fulfill({ json: body });
    });
    await page.getByRole("button", { name: "Generate gaps" }).click();
    job2Status = "succeeded";

    await expect(page.getByText("No compared method reports results under low-resource training data.")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("EVALUATION GAP")).toBeVisible();
    await expect(page.getByText("2 supporting papers")).toBeVisible();
    await expect(page.getByText("60% coverage")).toBeVisible();
    await expect(page.getByText("self-support passed")).toBeVisible();
    await expect(page.getByText("Evaluate the compared methods under a low-resource training regime.")).toBeVisible();

    await page.getByText("1 evidence span").click();
    await expect(page.getByText("we did not evaluate under low-resource conditions")).toBeVisible();
    await page.getByText("Why this confidence").click();
    await expect(page.getByText("2 of 2 papers support this reading")).toBeVisible();

    // setGapState POSTs to a *different* path (.../gaps/{gap_id}) than the
    // list/generate route mocked above (.../gaps) -- Playwright's glob
    // match is exact-suffix, so it needs its own route.
    await page.route(`**/api/v1/workspaces/${workspaceId}/gaps/gap_pw_1`, (route) =>
      route.fulfill({ json: { ...mockedGap, user_state: "accepted" } })
    );
    // flip the mocked list's state *before* accepting: the page refetches the
    // list the moment the accept lands, and a refetch that beat this line
    // would keep returning the gap as a candidate (a real, intermittent race)
    gapState = "accepted";
    await page.getByRole("button", { name: "Accept", exact: true }).click();
    // Accepting removes it from the still-active "Candidates" filter (the
    // list re-fetches with state=candidate and no longer matches it) --
    // switch filters to see the new state, same as curate-flow.spec.ts's
    // accepted/rejected trail-edge filter switch.
    await page.getByRole("button", { name: "Candidates" }).click();
    await expect(page.getByText("No candidate gaps")).toBeVisible({ timeout: 5_000 });
    await page.getByRole("button", { name: "Accepted" }).click();
    await expect(page.getByText("accepted", { exact: true })).toBeVisible({ timeout: 5_000 });
  });
});
