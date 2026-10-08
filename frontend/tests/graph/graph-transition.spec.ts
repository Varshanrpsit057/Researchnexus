// spec: the background becomes the research graph, in every background mode
// (remediation Phases 14-15).
//
// Opening the graph sends the background into its graph state and the
// graph's papers emerge from it; leaving gives the background back. The
// neural network condenses onto the papers, GhostFibers surges then dims to
// an ambient level behind them, and the still background fades -- always the
// one background that was already on screen, never swapped for another.
//
// The workspace and its graph are real: seed-trail-run.py runs the real trail
// pipeline over a run for the seed, and the workspace is created through the
// real API with this page's own session.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPERS = path.join(__dirname, "..", "workspaces");
const FIXTURE = path.join(__dirname, "..", "trail", "seed-trail-run.py");
const py = (args: string[]) => execFileSync(PYTHON, args);

async function graphWorkspace(page: Page): Promise<{ seedId: string; workspaceId: string }> {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Browse for a file" }).click();
  await (await chooser).setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
  await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
  const seedId = page.url().split("/papers/")[1].split("?")[0];
  py([path.join(HELPERS, "seed-real-profile.py"), seedId, "Graph Transition Seed"]);
  const stamp = Date.now();
  const runId = `run_pw_morph_${stamp}`;
  py([FIXTURE, "seed", seedId, runId, `m${stamp}`]);
  const token = await page.evaluate(() => window.localStorage.getItem("researchnexus.token"));
  const resp = await page.request.post("http://localhost:8000/api/v1/workspaces", {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: `Graph transition ${stamp}`, seed_paper_id: seedId, import_run_id: runId },
  });
  expect(resp.ok()).toBe(true);
  return { seedId, workspaceId: (await resp.json()).workspace_id };
}

/** Into the graph from the workspace (a client-side navigation, as a user
 * does), through the transition, then back out. */
async function throughTheGraph(page: Page, workspaceId: string, effect: string, effectEl: string) {
  await page.goto(`/workspace/${workspaceId}`);
  const background = page.getByTestId("background");
  await expect(background).toHaveAttribute("data-effect", effect, { timeout: 10_000 });
  const mounted = page.getByTestId(effectEl);
  await expect(mounted).toHaveAttribute("data-mode", "field");

  await page.getByRole("link", { name: /^Research graph/ }).click();
  const stage = page.getByTestId("graph-stage");
  await expect(stage).toHaveAttribute("data-phase", "intro", { timeout: 10_000 });
  // the background that was already there takes the graph state: not another one
  await expect(background).toHaveAttribute("data-mode", "graph");
  await expect(background).toHaveAttribute("data-effect", effect);
  await expect(mounted).toHaveAttribute("data-mode", "graph");
  await expect(stage).toHaveAttribute("data-phase", "settled", { timeout: 10_000 });
  await expect(stage.getByRole("button", { name: /\. Seed paper\. / })).toBeVisible();

  await page.goBack();
  await page.waitForURL(new RegExp(`/workspace/${workspaceId}$`));
  await expect(background).toHaveAttribute("data-mode", "field");
  await expect(mounted).toHaveAttribute("data-mode", "field");
}

test.describe("Background to graph", () => {
  let seedId: string | null = null;

  test.afterEach(() => {
    if (seedId) {
      py([path.join(HELPERS, "cleanup-seeded-profile.py"), seedId]);
      py([FIXTURE, "restore", seedId]);
    }
    seedId = null;
  });

  test("the neural network condenses into the graph and is given back", async ({ page }) => {
    await page.evaluate(() => window.localStorage.setItem("researchnexus.pref.background", "animated"));
    const ws = await graphWorkspace(page);
    seedId = ws.seedId;
    await throughTheGraph(page, ws.workspaceId, "neural", "constellation");
  });

  test("GhostFibers surges, dims behind the graph, and eases back", async ({ page }) => {
    await page.addInitScript(() => {
      (window as unknown as { __RN_GPU__: string }).__RN_GPU__ = "integrated";
    });
    const ws = await graphWorkspace(page);
    seedId = ws.seedId;
    await throughTheGraph(page, ws.workspaceId, "fibers", "ghost-fibers");
  });

  test("the still background fades behind the graph, with no animation", async ({ page }) => {
    // chosen: software drawing gets the light fibers since 2026-10-09
    await page.evaluate(() => window.localStorage.setItem("researchnexus.pref.background", "static"));
    const ws = await graphWorkspace(page);
    seedId = ws.seedId;
    await throughTheGraph(page, ws.workspaceId, "static", "static-background");
    await expect(page.getByTestId("background").locator("canvas")).toHaveCount(0);
  });
});
