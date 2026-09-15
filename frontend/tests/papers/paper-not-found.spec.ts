// spec: manual (single well-known critical flow; see Phase 15 completion report)
import { test, expect } from "../fixtures";

test.describe("Paper lookup", () => {
  test("shows an honest empty state for a paper id that was never uploaded", async ({ page }) => {
    // 1. Jump to a paper id that does not exist
    await page.getByRole("textbox", { name: /paper id/i }).fill("pap_does_not_exist");
    await page.getByRole("button", { name: "Open", exact: true }).click();

    // 2. See a clear "not found" state rather than a crash or blank page
    await expect(page.getByText("Paper not found")).toBeVisible();
  });
});
