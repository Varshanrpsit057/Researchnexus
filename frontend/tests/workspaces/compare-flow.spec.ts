// spec: Phase 10 (Paper Comparison) critical flow at /workspace/[id]/compare.
//
// The comparison under test is the real pipeline's output: seed-comparison.py
// runs app/services/synthesis/compare.py::build_comparison over the
// workspace's real papers (the uploaded seed's parsed text, and the
// discovered papers' abstracts) and stores it as POST .../compare would.
// Only the language model inside it is scripted (no BYOK key exists here);
// every value it proposes still has to pass the pipeline's own verbatim
// check, and one deliberately fails it. In the browser, the only mocks are
// the `me` flag saying a key is saved and the compare POST (it answers with
// the stored, real comparison). Everything else is the real backend.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page, Route } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const BACKEND = String.raw`H:\Researchnexus\backend`;
const HELPERS = __dirname;
const TRAIL_FIXTURE = path.join(__dirname, "..", "trail", "seed-trail-run.py");

const SIMILAR = "Phase 7 Fixture: Retrieval-Augmented Generators Revisited";
const COMPETING = "Phase 7 Fixture: A Competing Symbolic Approach";

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
    // intentional failures: the mocked 502 and the missing comparison's real 404
    if (m.type() === "error" && !/\b(502|404)\b/.test(m.text())) errors.push(m.text());
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

/** The table as the page shows it: heading row (title, meta), then each
 * field's row (label, then each cell's lines: its text, and its note). */
async function tableOnPage(page: Page): Promise<string[][][]> {
  return page
    .getByTestId("comparison-table")
    .locator("table")
    .evaluate((table) => {
      const text = (el: Element | null) => el?.textContent ?? "";
      const head = [...table.querySelectorAll("thead th")].map((th, i) =>
        i === 0 ? [text(th)] : [text(th.querySelector('[data-testid="paper-title"]')), text(th.querySelector('[data-testid="paper-meta"]'))],
      );
      const rows = [...table.querySelectorAll("tbody tr")].map((tr) => [
        [text(tr.querySelector("th"))],
        ...[...tr.querySelectorAll("td")].map((td) => [...td.querySelectorAll("[data-cell-text], [data-cell-note]")].map((el) => text(el))),
      ]);
      return [head, ...rows];
    });
}

/** "Export to Word", then the downloaded document's one table, read back by
 * an XML reader independent of the writer (backend/tests/docx_reader.py). */
async function exportedTable(page: Page): Promise<string[][][]> {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export to Word" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^Comparison - .+\.docx$/);
  const saved = test.info().outputPath(`comparison-${Date.now()}.docx`);
  await file.saveAs(saved);
  const doc = JSON.parse(execFileSync(PYTHON, ["-m", "tests.docx_reader", saved], { cwd: BACKEND }).toString());
  expect(doc.tables).toHaveLength(1);
  expect(doc.header_rows).toEqual([1]); // the heading row repeats on every page
  return doc.tables[0];
}

test.describe("Paper comparison", () => {
  let seedId: string | null = null;

  test.afterEach(() => {
    if (seedId) {
      py([path.join(HELPERS, "cleanup-seeded-profile.py"), seedId]);
      py([TRAIL_FIXTURE, "restore", seedId]);
    }
    seedId = null;
  });

  test("papers from a workspace compare side by side, every value quoted and every gap explained", async ({ page }) => {
    // 1. A real workspace: the uploaded seed plus a real discovery run's papers.
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Compare Flow Seed"]);
    const stamp = Date.now();
    const runId = `run_pw_compare_${stamp}`;
    py([TRAIL_FIXTURE, "seed", seedId, runId, `c${stamp}`]);
    await page.route("**/api/v1/papers/*/discover-related", (route) =>
      route.fulfill({ json: { job: { job_id: "job_pw_cmp", kind: "discover", status: "queued", poll_url: "/api/v1/jobs/job_pw_cmp" } } }),
    );
    await page.route("**/api/v1/jobs/job_pw_cmp", (route) =>
      route.fulfill({ json: { job_id: "job_pw_cmp", status: "succeeded", progress: { stage: "done" }, result_ref: runId, error: null } }),
    );
    const consoleErrors = collectConsoleErrors(page);
    await page.goto(`/discover/${seedId}`);
    await expect(page.getByText(SIMILAR)).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Create workspace", exact: true }).click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 15_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

    // two abstract-only papers join through the real UI (joining indexes their abstracts)
    await page.getByRole("button", { name: "Add papers" }).click();
    await page.getByRole("checkbox", { name: new RegExp(SIMILAR) }).check();
    await page.getByRole("checkbox", { name: new RegExp(COMPETING) }).check();
    await page.getByRole("button", { name: "Add 2 papers" }).click();
    await expect(page.getByRole("heading", { name: /^Papers\s*3$/ })).toBeVisible({ timeout: 15_000 });

    // 2. Workspace -> Compare, from the overview's comparison station.
    await page.getByRole("link", { name: /^Comparison\s*:/ }).click();
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/compare$`));
    await expect(page.getByRole("heading", { level: 1, name: "Compare papers" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "No comparison yet" })).toBeVisible({ timeout: 10_000 });
    const papers = page.getByRole("list", { name: "Papers to compare" }).getByRole("button");
    await expect(papers).toHaveCount(3);
    await expect(page.getByRole("button", { pressed: true }).filter({ hasText: /Synthetic Test Paper/ })).toBeVisible();
    // no key saved (real): running is off and says why
    await expect(page.getByText("No working LLM provider key is saved, so a comparison can't run yet.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Compare 3 papers" })).toBeDisabled();

    // 3. The real pipeline's comparison of these papers.
    const stored = JSON.parse(py([path.join(HELPERS, "seed-comparison.py"), workspaceId]));
    await page.reload();
    const similarId = stored.rows.find((r: { cells: Record<string, { text: string | null }> }) => r.cells.method.text === "Generators that read retrieved passages").paper_id;
    await expect(page.getByText(/3 papers side by side, 4 fields\. \d+ of 12 values are stated/)).toBeVisible({ timeout: 10_000 });
    const methodOfSimilar = page.getByRole("button", { name: new RegExp(`^Method for ${SIMILAR}: Generators that read retrieved passages`) });
    await expect(methodOfSimilar).toBeVisible();
    await expect(page.getByRole("button", { name: /^Results for .*Synthetic Test Paper.*: 58\.6 F1/ })).toBeVisible();
    // gaps say why they are gaps (wide screens show a table, phones one field at a time)
    const view = page.locator('[data-testid="comparison-table"], [data-testid="comparison-by-field"]').filter({ visible: true });
    await expect(view.getByText("Unverified").first()).toBeVisible();
    await expect(view.getByText("Not stated").first()).toBeVisible();

    // 4. A value's passage: verbatim, located, and a way to its paper.
    await methodOfSimilar.click();
    const evidence = page.getByRole("complementary");
    await expect(evidence.getByRole("heading", { name: "Method: Generators that read retrieved passages" })).toBeVisible();
    await expect(evidence).toContainText("Quoted from Abstract, the only text of this paper in the workspace");
    await expect(evidence).toContainText("We revisit generators that read retrieved passages");
    await expect(evidence.getByRole("link", { name: "Show in graph" })).toHaveAttribute("href", `/workspace/${workspaceId}/graph?paper=${similarId}`);
    await page.keyboard.press("Escape");
    await expect(evidence).toHaveCount(0);

    // 4b. Export to Word: the document's table is the page's table -- every
    // heading in full, every row and cell, in the same order.
    if (test.info().project.name === "chromium") {
      const onPage = await tableOnPage(page);
      expect(onPage[0][0]).toEqual(["Field"]);
      expect(onPage[0].slice(1).map((h) => h[0])).toEqual(expect.arrayContaining([expect.stringMatching(/Synthetic Test Paper/), SIMILAR, COMPETING]));
      expect(onPage).toHaveLength(1 + 4); // a heading row and the four fields
      expect(await exportedTable(page)).toEqual(onPage);
    }

    // 5. Remove a paper from the comparison, then bring it back.
    // wide screens have a remove button on each paper's column; the paper chips work everywhere
    await page.getByRole("button", { name: /^Papers and fields/ }).click();
    const chip = page.getByRole("list", { name: "Papers to compare" }).getByRole("button", { name: new RegExp(COMPETING) });
    if (test.info().project.name === "chromium") await page.getByRole("button", { name: `Remove ${COMPETING} from the comparison` }).click();
    else await chip.click();
    await expect(chip).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByText(/2 papers side by side/)).toBeVisible();
    await expect(page.getByRole("button", { name: new RegExp(`^Method for ${COMPETING}`) })).toHaveCount(0);
    if (test.info().project.name === "chromium") {
      // only the columns on screen are exported
      const onPage = await tableOnPage(page);
      expect(onPage[0]).toHaveLength(3);
      expect(onPage[0].map((h) => h[0])).not.toContain(COMPETING);
      expect(await exportedTable(page)).toEqual(onPage);
    }
    await chip.click();
    await expect(page.getByText(/3 papers side by side/)).toBeVisible();

    // 6. Run it again: a failure says so; a success shows the (stored, real) result.
    await claimAKey(page);
    let posts = 0;
    const bodies: Record<string, unknown>[] = [];
    await page.route(`**/api/v1/workspaces/${workspaceId}/compare`, async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      posts += 1;
      bodies.push(route.request().postDataJSON());
      await new Promise((r) => setTimeout(r, 600));
      if (posts === 1) return route.fulfill({ status: 502, json: { detail: { error: { code: "provider_error", message: "x" } } } });
      const latest = await route.fetch({ method: "GET" });
      return route.fulfill({ response: latest });
    });
    await page.reload();
    await page.getByRole("button", { name: /^Papers and fields/ }).click();
    await page.getByRole("button", { name: "Compare 3 papers again" }).click();
    await expect(page.getByText(/Reading 3 papers and checking every value/)).toBeVisible();
    await expect(page.getByText("The comparison didn't finish. Try again in a moment.")).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Compare 3 papers again" }).click();
    await expect(page.getByRole("button", { name: new RegExp(`^Method for ${SIMILAR}`) })).toBeVisible({ timeout: 10_000 });
    expect(bodies[0]).toMatchObject({ schema: ["method", "dataset", "metric", "result"] });
    expect((bodies[0].paper_ids as string[]).length).toBe(3);

    // 7. The way in from anywhere, and the old URL.
    await page.goto("/compare");
    const entry = page.locator(`a[href="/workspace/${workspaceId}/compare"]`);
    await expect(entry).toBeVisible({ timeout: 10_000 });
    await expect(entry).toContainText("3 papers");
    await page.goto(`/workspaces/${workspaceId}/compare`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/compare$`));

    expect(consoleErrors).toEqual([]);
  });

  test("a workspace with only its seed explains what a comparison needs, and a failed load offers a retry", async ({ page }) => {
    seedId = await uploadSeed(page);
    py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Compare Empty Seed"]);
    await page.reload();
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];
    await page.goto(`/workspace/${workspaceId}/compare`);
    await expect(page.getByRole("heading", { name: "A comparison needs two papers" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: "Add papers" })).toHaveAttribute("href", `/workspace/${workspaceId}#papers`);
    await expect(page.getByRole("link", { name: "Discover related papers" })).toHaveAttribute("href", `/discover/${seedId}`);

    // The server failing is simulated for this one response; the page's handling is what's tested.
    await page.route(`**/api/v1/workspaces/${workspaceId}/compare`, (route) =>
      route.fulfill({ status: 500, json: { detail: { error: { code: "internal", message: "internal error" } } } }),
    );
    await page.reload();
    await expect(page.getByText("Could not load this workspace's comparison.")).toBeVisible({ timeout: 10_000 });
    await page.unroute(`**/api/v1/workspaces/${workspaceId}/compare`);
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("heading", { name: "A comparison needs two papers" })).toBeVisible({ timeout: 10_000 });
  });

  test("a missing workspace says so", async ({ page }) => {
    await page.goto("/workspace/ws_pw_compare_missing/compare");
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
  });
});
