// spec: the Papers library, the Workspaces list and the activity log in the
// app's one dark world (2026-10-07). Real backend throughout; the seed's
// research profile is seeded (analysis needs a model key this environment
// doesn't have), as in every workspace spec.
import path from "node:path";
import { execFileSync } from "node:child_process";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const HELPERS = __dirname;

test.describe("Library, workspaces and activity", () => {
  let seedId: string | null = null;
  test.afterEach(() => {
    if (seedId) execFileSync(PYTHON, [path.join(HELPERS, "cleanup-seeded-profile.py"), seedId]);
    seedId = null;
  });

  test("a paper's workspace is named on its page, listed with its seed and counts, renamed, and deleted after a confirmation", async ({ page }) => {
    // 1. An analysed paper, and a workspace with just it
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    await (await chooser).setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });
    seedId = page.url().split("/papers/")[1].split(/[?#]/)[0];
    execFileSync(PYTHON, [path.join(HELPERS, "seed-real-profile.py"), seedId, "Workspaces Page Seed"]);
    await page.reload();
    const title = `Workspaces page ${Date.now()}`;
    await page.getByText("Skip discovery, start a workspace with just this paper").click();
    const dialog = page.getByRole("dialog", { name: "Create a workspace" });
    await dialog.getByRole("textbox", { name: "Title" }).fill(title);
    await dialog.getByRole("button", { name: "Create workspace" }).click();
    await page.waitForURL(/\/workspace\/ws_/, { timeout: 10_000 });
    const workspaceId = page.url().split("/workspace/")[1].split(/[/?#]/)[0];

    // 2. The paper's page names the workspace holding it
    await page.goto(`/papers/${seedId}`);
    await expect(page.getByTestId("paper-workspaces").getByRole("link", { name: title })).toHaveAttribute("href", `/workspace/${workspaceId}`);

    // 3. The library lists the paper, in that workspace, analysed
    await page.goto("/papers");
    await page.getByRole("searchbox", { name: "Search your papers" }).fill("Synthetic Test Paper");
    const row = page.getByTestId("library").getByRole("listitem").filter({ hasText: "Synthetic Test Paper" }).first();
    await expect(row).toContainText("Research profile");
    await expect(row.getByRole("link", { name: title })).toHaveAttribute("href", `/workspace/${workspaceId}`);
    await page.getByRole("button", { name: /^Not analysed \d+$/ }).click();
    await expect(page.getByTestId("library").getByText("Synthetic Test Paper")).toHaveCount(0);

    // 4. The workspaces list: its seed and what it holds; renamed in place
    await page.goto("/workspaces");
    const listed = page.getByTestId(`workspace-row-${workspaceId}`);
    await expect(listed).toContainText("Seeded from");
    await expect(listed).toContainText("1 paper");
    await expect(listed).toContainText("0 connections");
    await listed.getByRole("button", { name: `Rename ${title}` }).click();
    await listed.getByRole("textbox", { name: "Workspace name" }).fill(`${title} (renamed)`);
    await listed.getByRole("button", { name: "Save" }).click();
    await expect(listed.getByRole("link", { name: `${title} (renamed)` })).toBeVisible();

    // 5. Its activity log: nothing has run yet; the old address forwards there
    await page.goto(`/workspaces/${workspaceId}/activity`);
    await page.waitForURL(new RegExp(`/workspace/${workspaceId}/activity$`));
    await expect(page.getByRole("heading", { level: 1, name: "Activity" })).toBeVisible();
    await expect(page.getByText("Nothing has run here yet")).toBeVisible();

    // 6. Deleting asks first, says what stays, then really deletes
    await page.goto("/workspaces");
    await listed.getByRole("button", { name: `Delete ${title} (renamed)` }).click();
    const confirm = page.getByRole("dialog", { name: `Delete ${title} (renamed)?` });
    await expect(confirm).toContainText("Its 1 paper stay in your library.");
    await confirm.getByRole("button", { name: "Keep it" }).click();
    await expect(listed).toBeVisible();
    await listed.getByRole("button", { name: `Delete ${title} (renamed)` }).click();
    await confirm.getByRole("button", { name: "Delete workspace" }).click();
    await expect(page.getByTestId(`workspace-row-${workspaceId}`)).toHaveCount(0);
    await page.goto(`/workspace/${workspaceId}`);
    await expect(page.getByRole("heading", { name: "Workspace not found" })).toBeVisible({ timeout: 10_000 });
  });
});
