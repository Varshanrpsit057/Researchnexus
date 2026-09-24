// spec: adding many papers to an existing workspace.
//
// Everything here runs against the real backend: real uploads, real parse
// jobs, and the real add-papers endpoint. The only helper is the persisted
// seed profile (analyze is LLM-gated in this environment; see
// tests/workspaces/curate-flow.spec.ts) and a generator for fresh PDFs,
// since the backend deduplicates uploads by file hash.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPERS = path.join(__dirname, "..", "workspaces");

function seedProfile(paperId: string, title: string) {
  execFileSync(PYTHON, [path.join(HELPERS, "seed-real-profile.py"), paperId, title]);
}

function cleanupSeededProfile(paperId: string) {
  execFileSync(PYTHON, [path.join(HELPERS, "cleanup-seeded-profile.py"), paperId]);
}

function makePdfs(outDir: string, count: number): string[] {
  const out = execFileSync(PYTHON, [path.join(__dirname, "make-upload-pdfs.py"), outDir, String(count), String(Date.now())]);
  return out.toString().trim().split(/\r?\n/);
}

test.describe("Adding papers to a workspace", () => {
  let seededPaperId: string | null = null;

  test.afterEach(() => {
    if (seededPaperId) cleanupSeededProfile(seededPaperId);
    seededPaperId = null;
  });

  test("several PDFs uploaded at once are parsed and added, and several ids can be added together", async ({ page }, testInfo) => {
    // 1. A real seed paper and a workspace around it.
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    await (await chooser).setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    const seedId = page.url().split("/papers/")[1].split("?")[0];
    seededPaperId = seedId;
    seedProfile(seedId, "Add Papers Seed");
    await page.reload();
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    await page.getByRole("dialog", { name: "Create a workspace" }).getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    await expect(page.getByRole("heading", { name: /^Papers\s*1$/ })).toBeVisible({ timeout: 10_000 });

    // 2. Three fresh PDFs plus a file that isn't a PDF, chosen in one go.
    const pdfs = makePdfs(testInfo.outputPath("uploads"), 3);
    const notes = testInfo.outputPath("uploads", "notes.txt");
    fs.writeFileSync(notes, "not a paper");

    await page.getByRole("button", { name: "Add papers" }).click();
    const files = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Choose PDFs" }).click();
    await (await files).setFiles([...pdfs, notes]);

    const row = (name: string) => page.getByRole("listitem").filter({ hasText: name });
    await expect(row("notes.txt")).toContainText("Not a PDF file.");
    for (const pdf of pdfs) {
      await expect(row(path.basename(pdf))).toContainText("Added", { timeout: 45_000 });
    }
    await expect(page.getByRole("heading", { name: /^Papers\s*4$/ })).toBeVisible();

    // 3. Several ids at once: one already in the workspace, one that doesn't exist.
    const memberHref = await page
      .locator("#papers ul")
      .last()
      .getByRole("link")
      .filter({ hasText: "Upload Fixture" })
      .first()
      .getAttribute("href");
    const memberId = memberHref!.split("/papers/")[1];
    const input = page.getByLabel("Add by paper ID");
    await input.fill(`${memberId}, pap_does_not_exist_pw`);
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByText("1 paper already in this workspace.")).toBeVisible();
    await expect(page.getByText("No paper found for pap_does_not_exist_pw")).toBeVisible();
    // only the id that still needs attention stays in the box
    await expect(input).toHaveValue("pap_does_not_exist_pw");
    await expect(page.getByRole("heading", { name: /^Papers\s*4$/ })).toBeVisible();

    // 4. It all persisted.
    await page.reload();
    await expect(page.getByRole("heading", { name: /^Papers\s*4$/ })).toBeVisible({ timeout: 10_000 });
  });
});
