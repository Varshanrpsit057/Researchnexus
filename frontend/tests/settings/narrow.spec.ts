// spec: Settings in a window narrower than a desktop's (2026-10-09). At about
// 1,000 CSS px (a laptop at 125% scaling) the sections became one row that
// scrolled sideways with no sign of it: "Appearance" and "Service & about"
// were off-screen, and the row made the page wider than the window, cutting
// off the pane's right edge.
import { test, expect } from "../fixtures";

const SECTIONS = ["Account", "Library & workspaces", "Discovery defaults", "Sources & full text", /^Language models/, "Model usage", "Appearance", "Service & about"];

for (const width of [1000, 760, 390]) {
  test(`at ${width} px every settings section can be seen and opened, and nothing runs off the page`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/settings");
    const nav = page.getByRole("navigation", { name: "Settings sections" });
    await expect(nav.getByRole("link", { name: "Account" })).toBeVisible({ timeout: 10_000 });
    for (const name of SECTIONS) {
      const link = nav.getByRole("link", { name });
      await expect(link).toBeInViewport({ ratio: 1 });
    }
    await nav.getByRole("link", { name: "Appearance" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Appearance" })).toBeVisible();
    await expect(page.getByRole("group", { name: "Background" }).getByRole("button", { name: "Static" })).toBeInViewport({ ratio: 1 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}
