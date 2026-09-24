// spec: the global network background takes its light path.
//
// In Chromium the background should draw with WebGL2 inside a Web Worker
// (OffscreenCanvas), keeping its per-frame work off the page's own thread.
// Canvas 2D is the fallback, never the default here. Renderer parity (both
// draw the same seeded frame to within a fraction of a percent) was checked
// when the renderers were written; this guards the wiring.
import { test, expect } from "@playwright/test";

test.describe("Global background", () => {
  test("renders with WebGL2 in a worker, without console errors, and survives navigation", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => msg.type() === "error" && errors.push(msg.text()));
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/");
    const canvas = page.locator("canvas[data-renderer]");
    await expect(canvas).toHaveAttribute("data-renderer", "webgl2");
    await expect(canvas).toHaveAttribute("data-thread", "worker");
    const box = await canvas.boundingBox();
    const viewport = page.viewportSize()!;
    expect(box?.width).toBe(viewport.width);
    expect(box?.height).toBe(viewport.height);

    // mounted once in the root layout: a client-side navigation keeps the same canvas
    await canvas.evaluate((el) => el.setAttribute("data-probe", "kept"));
    await page.getByRole("link", { name: "Sign in" }).first().click();
    await page.waitForURL(/\/sign-in/);
    await expect(page.locator("canvas[data-probe='kept']")).toHaveCount(1);

    expect(errors).toEqual([]);
  });

  test("falls back to Canvas 2D when asked, drawing a full-size frame", async ({ page }) => {
    await page.addInitScript(() => {
      (window as unknown as { __RN_CONSTELLATION__: object }).__RN_CONSTELLATION__ = { renderer: "canvas2d", thread: "main" };
    });
    await page.goto("/");
    const canvas = page.locator("canvas[data-renderer]");
    await expect(canvas).toHaveAttribute("data-renderer", "canvas2d");
    await expect(canvas).toHaveAttribute("data-thread", "main");
    const lit = await canvas.evaluate((el) => {
      const c = el as HTMLCanvasElement;
      const data = c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      for (let i = 3; i < data.length; i += 4) if (data[i] > 40) n++;
      return n / (c.width * c.height);
    });
    // a dense field: a real share of the canvas is drawn, not a blank or stub frame
    expect(lit).toBeGreaterThan(0.02);
  });
});
