// spec: Phase 5 (Discovery) critical flow.
//
// Discovery's external-API strategies (arXiv, OpenAlex, Semantic Scholar,
// Crossref) are not reachable from this sandboxed test environment (see
// tests/papers/discover-flow.spec.ts's own header for the live-verified
// reason), so the job/related calls are mocked at the network layer here
// too. Unlike that spec, this one also exercises the real
// paper-selection -> workspace flow, which needs a genuinely *persisted*
// profile (the backend's own SeedNotAnalyzed check runs server-side) --
// analyze is LLM-gated with no working BYOK key in this environment, so
// the same seed-real-profile.py helper Slice 3 uses seeds one directly.
import path from "node:path";
import { execFileSync } from "node:child_process";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;

function seedProfile(paperId: string, title: string) {
  execFileSync(PYTHON, [path.join(__dirname, "..", "workspaces", "seed-real-profile.py"), paperId, title]);
}

function cleanupSeededProfile(paperId: string) {
  execFileSync(PYTHON, [path.join(__dirname, "..", "workspaces", "cleanup-seeded-profile.py"), paperId]);
}

test.describe("Discovery", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) cleanupSeededProfile(seededPaperId);
    seededPaperId = null;
  });

  test("auto-starts a run, renders ranked results with explanations, and creating a workspace from a selection persists for real", async ({ page }) => {
    // 1. Real upload, then a real, persisted profile (see file header).
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    const paperId = page.url().split("/papers/")[1].split("?")[0];
    seededPaperId = paperId;
    seedProfile(paperId, "Discover Flow Seed Paper");

    // 2. Mock only the external-API-dependent discovery calls.
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_discover", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_discover" } } })
    );
    let attempt = 0;
    await page.route("**/api/v1/jobs/job_pw_discover", (route) => {
      attempt += 1;
      const body =
        attempt < 2
          ? { job_id: "job_pw_discover", status: "running", progress: { stage: "ranking" }, result_ref: null, error: null }
          : { job_id: "job_pw_discover", status: "succeeded", progress: { stage: "done" }, result_ref: "run_pw_discover_001", error: null };
      route.fulfill({ json: body });
    });
    await page.route(`**/api/v1/papers/${paperId}/related*`, (route) =>
      route.fulfill({
        json: {
          run: {
            run_id: "run_pw_discover_001",
            seed_paper_id: paperId,
            strategies_succeeded: ["semantic", "citation"],
            strategies_failed: ["keyword"],
            counts: { raw: 40, after_dedupe: 22, after_filter: 2 },
            extra_citation_hop_used: true,
            weights_version: "v1",
          },
          results: [
            {
              paper: {
                id: "pap_pw_discover_related_1",
                title: "Dense Passage Retrieval for Open-Domain Question Answering",
                authors: ["V. Karpukhin"],
                year: 2020,
                venue: "EMNLP",
                doi: null,
                url: null,
              },
              discovery_methods: ["semantic_doc", "citation"],
              citation_relationship: "cites_seed",
              signals: { semantic_doc: 0.82, semantic_chunk: null, problem_sim: 0.71, method_sim: 0.65, dataset_overlap: null, citation: 1.0, recency: 0.4 },
              weights_version: "v1",
              fused_score: 0.78,
              rerank_score: null,
              final_rank: 1,
              band: "high",
              explanation: {
                bullet_reasons: ["cites the seed paper directly", "high semantic similarity on the core method"],
                prose: "This paper cites the seed directly and shares a strong semantic match on its core retrieval method.",
                signals_used: ["semantic_doc", "citation"],
                template_only: true,
              },
            },
            {
              paper: {
                id: "pap_pw_discover_related_2",
                title: "A Low-Confidence Loosely Related Paper",
                authors: [],
                year: 2019,
                venue: null,
                doi: null,
                url: null,
              },
              discovery_methods: ["keyword"],
              citation_relationship: "none",
              signals: { semantic_doc: 0.31, semantic_chunk: null, problem_sim: null, method_sim: null, dataset_overlap: null, citation: null, recency: 0.6 },
              weights_version: "v1",
              fused_score: 0.31,
              rerank_score: null,
              final_rank: 2,
              band: "low",
              explanation: null,
            },
          ],
        },
      })
    );

    // 3. Reaching the page is the only trigger needed -- it auto-starts.
    await page.goto(`/discover/${paperId}`);
    await expect(page.getByText("Ranking candidates against the seed profile")).toBeVisible();
    await expect(page.getByText("Dense Passage Retrieval for Open-Domain Question Answering")).toBeVisible({ timeout: 5_000 });
    await expect(page).toHaveURL(new RegExp(`/discover/${paperId}\\?run=run_pw_discover_001`));

    // 4. Transparent ranking: real per-signal scores and the plain-language
    //    explanation are visible without an extra click.
    await expect(page.getByText("#1")).toBeVisible();
    await expect(page.getByText("This paper cites the seed directly")).toBeVisible();
    await expect(page.getByText("semantic").first()).toBeVisible();
    await expect(page.getByText("cites seed")).toBeVisible();
    await expect(page.getByText("A Low-Confidence Loosely Related Paper")).toBeVisible();

    // 5. Filtering by confidence band actually narrows the real list.
    await page.getByRole("button", { name: "High", exact: true }).click();
    await expect(page.getByText("Dense Passage Retrieval for Open-Domain Question Answering")).toBeVisible();
    await expect(page.getByText("A Low-Confidence Loosely Related Paper")).not.toBeVisible();
    await page.getByRole("button", { name: "All", exact: true }).click();
    await expect(page.getByText("A Low-Confidence Loosely Related Paper")).toBeVisible();

    // 6. Selecting a result is a real, verified UI mechanic (the sticky
    //    bar's label updates for real), but the workspace-creation call
    //    that follows stays real and unmocked too -- and the selected id
    //    here ("pap_pw_discover_related_1") is a mocked discovery result
    //    that was never actually ingested, so carrying it into a real
    //    addPapers call would 404. Deselect before the real create call,
    //    the same scoping decision curate-flow.spec.ts already made ("no
    //    related papers pre-selected -- discovery itself is [a different]
    //    slice's concern"); that spec's own paper-add coverage is where a
    //    genuinely-ingested paper is added to a workspace for real.
    const selectButton = page.getByRole("button", { name: /Select Dense Passage Retrieval/ });
    await selectButton.click();
    await expect(page.getByRole("button", { name: /Create workspace with 1 paper/ })).toBeVisible();
    await selectButton.click();
    await expect(page.getByRole("button", { name: "Create workspace", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Create workspace", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Create a workspace" });
    await expect(dialog.getByText("Only", { exact: false })).toBeVisible();
    await dialog.getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspaces\/ws_/, { timeout: 10_000 });
  });

  test("a seed paper with no profile yet cannot start discovery", async ({ page }) => {
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    const paperId = page.url().split("/papers/")[1].split("?")[0];

    await page.goto(`/discover/${paperId}`);
    await expect(page.getByText("Could not start discovery")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("needs a research profile first", { exact: false })).toBeVisible();
  });
});
