// spec: Slice 7 (Gap -> Direction) critical flow.
//
// Direction generation is LLM-gated and no working BYOK key exists in this
// environment, so the generate POST is mocked for the render/accept test
// below. The accepted-gaps checklist that gates it, though, needs a real
// persisted gap with user_state="accepted" AND self_support_passed=true
// (see services/directions/pipeline.py's build_directions) -- gap
// generation is itself LLM-gated (Slice 6's concern), so that gap is
// seeded directly through the repository layer, same reasoning as every
// other seed script beside this spec. The first test below never mocks
// the generate POST at all, proving the real, unmocked llm_key_required
// failure the same way chat-flow.spec.ts and gap-flow.spec.ts already do
// for their own generation endpoints.
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

function seedAcceptedGap(gapId: string, seedPaperId: string, secondPaperId: string, workspaceId: string) {
  execFileSync(PYTHON, [path.join(__dirname, "seed-accepted-gap.py"), gapId, seedPaperId, secondPaperId, workspaceId]);
}

function cleanupSeededProfile(paperId: string) {
  execFileSync(PYTHON, [path.join(__dirname, "cleanup-seeded-profile.py"), paperId]);
}

async function createWorkspaceWithAcceptedGap(
  page: import("@playwright/test").Page,
  label: string,
  gapId: string
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
  await page.waitForURL(/\/workspaces\/ws_/, { timeout: 10_000 });
  const workspaceId = page.url().split("/workspaces/")[1].split("/")[0].split("?")[0];

  const secondPaperId = `pap_pw_dir_${Date.now()}`;
  seedSecondPaperAndEdge(seedPaperId, secondPaperId, workspaceId);
  await page.goto(`/workspaces/${workspaceId}/papers`);
  await page.getByLabel("Add a paper by ID").fill(secondPaperId);
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText(secondPaperId)).toBeVisible({ timeout: 5_000 });

  seedAcceptedGap(gapId, seedPaperId, secondPaperId, workspaceId);

  return { workspaceId, seedPaperId, secondPaperId };
}

test.describe("Gap -> Direction", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) cleanupSeededProfile(seededPaperId);
    seededPaperId = null;
  });

  test("an accepted gap appears in the checklist, and generating without a saved key shows the real error", async ({ page }) => {
    const { workspaceId, seedPaperId } = await createWorkspaceWithAcceptedGap(page, "Direction Flow Seed Paper A", `gap_pw_dir_real_1_${Date.now()}`);
    seededPaperId = seedPaperId;

    await page.goto(`/workspaces/${workspaceId}/directions`);
    await expect(page.getByText("No compared method reports results under low-resource training data.")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("No directions yet")).toBeVisible();

    // Real, unmocked POST: this sandbox genuinely has no working LLM key.
    await page.locator("label", { hasText: "No compared method reports results" }).click();
    await page.getByRole("button", { name: /Generate from 1 gap/ }).click();
    await expect(
      page.getByText("No working LLM provider key is saved yet. Add one in Settings, then generate directions again.")
    ).toBeVisible({ timeout: 5_000 });
  });

  test("generating directions renders an evidence-backed proposal, surfaces the drop/skip funnel, and you can accept it", async ({ page }) => {
    const gapId = `gap_pw_dir_real_2_${Date.now()}`;
    const { workspaceId, seedPaperId, secondPaperId } = await createWorkspaceWithAcceptedGap(
      page,
      "Direction Flow Seed Paper B",
      gapId
    );
    seededPaperId = seedPaperId;

    const mockedDirection = {
      direction_id: "dir_pw_1",
      workspace_id: workspaceId,
      gap_id: gapId,
      proposal: "Benchmark retrieval-augmented generation against dense retrieval under a shared low-resource split.",
      motivation: "Neither compared paper reports results with limited training data, leaving the comparison untested there.",
      supporting_evidence: [] as unknown[],
      related_papers: [seedPaperId, secondPaperId],
      suggested_method: "Few-shot fine-tuning with a fixed low-resource split",
      possible_dataset: "Natural Questions (low-resource subset)",
      evaluation_strategy: "Report exact match and F1 at 1%, 5%, and 10% of the original training data.",
      risks: ["Low-resource results may not generalize to full-scale training."],
      kind: "evidence_backed_inference",
      critique: { novelty: 0.7, specificity: 0.8, feasibility: 0.9, groundedness: 0.85 },
      confidence: "medium",
      confidence_basis: { agreement: "grounded in both papers' own limitations sections" },
      flags: [] as string[],
      user_state: "candidate",
      generated_at: "2026-01-01T00:00:00Z",
      generator_model: "playwright-mock",
    };

    await page.route(`**/api/v1/workspaces/${workspaceId}/directions*`, (route) => {
      if (route.request().method() === "POST") {
        route.fulfill({
          json: {
            directions: [mockedDirection],
            requested: 2,
            generated: 1,
            skipped_not_accepted: 0,
            skipped_not_found: 1,
            dropped_unsupported: 1,
          },
        });
      } else {
        const url = new URL(route.request().url());
        const state = url.searchParams.get("state");
        const shouldInclude = state === null || state === mockedDirection.user_state;
        route.fulfill({ json: { directions: shouldInclude ? [mockedDirection] : [] } });
      }
    });

    await page.goto(`/workspaces/${workspaceId}/directions`);
    await page.locator("label", { hasText: "No compared method reports results" }).click();
    await page.getByRole("button", { name: /Generate from 1 gap/ }).click();

    await expect(page.getByText("Generated 1 of 2 requested.")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("1 proposed direction lacked sufficient evidence and was dropped.")).toBeVisible();
    await expect(page.getByText("1 gap skipped (not found).")).toBeVisible();

    await expect(page.getByText("Benchmark retrieval-augmented generation against dense retrieval")).toBeVisible();
    await expect(page.getByText("evidence backed inference")).toBeVisible();
    await expect(page.getByText("Few-shot fine-tuning with a fixed low-resource split")).toBeVisible();
    await expect(page.getByText("Natural Questions (low-resource subset)")).toBeVisible();
    await expect(page.getByText("Neither compared paper reports results")).toBeVisible();
    await expect(page.getByText("Report exact match and F1")).toBeVisible();
    await expect(page.getByText("Low-resource results may not generalize")).toBeVisible();
    await expect(page.getByText("novelty")).toBeVisible();
    await expect(page.getByText("0.7")).toBeVisible();

    await page.getByText("Why this confidence").click();
    await expect(page.getByText("grounded in both papers' own limitations sections")).toBeVisible();

    const secondPaperLink = page.getByRole("link", { name: secondPaperId });
    await expect(secondPaperLink).toBeVisible();
    await expect(secondPaperLink).toHaveAttribute("href", `/papers/${secondPaperId}`);

    mockedDirection.user_state = "accepted";
    await page.route(`**/api/v1/workspaces/${workspaceId}/directions/dir_pw_1`, (route) =>
      route.fulfill({ json: mockedDirection })
    );
    await page.getByRole("button", { name: "Accept", exact: true }).click();
    await expect(page.getByText("accepted", { exact: true })).toBeVisible({ timeout: 5_000 });
  });
});
