// spec: manual (single well-known critical flow; see Phase 15 completion report)
import path from "node:path";
import { test, expect } from "../fixtures";

test.describe("Paper upload", () => {
  test("uploading a PDF parses it and lands on its detail page", async ({ page }) => {
    // 1. Choose a real PDF via the hidden file input behind "Browse for a file"
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse for a file" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(process.cwd(), "tests", "fixtures", "sample-paper.pdf"));

    // 2. Parsing finishes and the app redirects to the new paper's detail page
    await page.waitForURL(/\/papers\/pap_/, { timeout: 15_000 });

    // 3. The really-extracted title renders in the page header
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Retrieval-Augmented Generation");

    // 4. It is in the reader's library, by its real title and as their upload
    await page.goto("/papers");
    const row = page.getByTestId("library").getByRole("listitem").filter({ hasText: "Retrieval-Augmented Generation" }).first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row).toContainText("Uploaded");
    await page.getByRole("button", { name: /^Uploaded \d+$/ }).click();
    await expect(page.getByTestId("library")).toContainText("Retrieval-Augmented Generation");
  });
});
