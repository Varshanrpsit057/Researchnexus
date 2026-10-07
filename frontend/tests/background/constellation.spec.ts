// spec: the one global background, by device and setting (remediation Phase 14).
//
// Auto picks from the graphics the browser really draws with: the neural
// network with a dedicated GPU, GhostFibers without one, a still background
// when graphics run in software -- Playwright's own headless Chromium draws
// in software (SwiftShader), so that is what Auto sees here unless a test
// launches Chromium on the real GPU. Explicit Animated / Static choices
// override Auto. Exactly one effect is ever mounted.
import { test, expect, type Page } from "@playwright/test";

function background(page: Page) {
  return page.getByTestId("background");
}

async function choose(page: Page, choice: "auto" | "animated" | "static") {
  await page.addInitScript((c) => window.localStorage.setItem("researchnexus.pref.background", c), choice);
}

/** Whether the background region changes between two frames (once the
 * page's own entrance animations have finished). */
async function animating(page: Page): Promise<boolean> {
  await page.waitForTimeout(2000);
  const clip = { x: 0, y: 500, width: 1200, height: 200 };
  const a = await page.screenshot({ clip });
  await page.waitForTimeout(700);
  const b = await page.screenshot({ clip });
  return !a.equals(b);
}

test.describe("Global background", () => {
  test("Animated runs the neural network with WebGL2 in a worker, and survives navigation", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => msg.type() === "error" && errors.push(msg.text()));
    page.on("pageerror", (err) => errors.push(err.message));
    await choose(page, "animated");

    await page.goto("/");
    await expect(background(page)).toHaveAttribute("data-effect", "neural");
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

  test("the neural network falls back to Canvas 2D when asked, drawing a full-size frame", async ({ page }) => {
    await choose(page, "animated");
    await page.addInitScript(() => {
      (window as unknown as { __RN_CONSTELLATION__: object }).__RN_CONSTELLATION__ = { renderer: "canvas2d", thread: "main" };
    });
    await page.goto("/");
    const canvas = page.locator("canvas[data-renderer]");
    await expect(canvas).toHaveAttribute("data-renderer", "canvas2d");
    await expect(canvas).toHaveAttribute("data-thread", "main");
    const lit = () =>
      canvas.evaluate((el) => {
        const c = el as HTMLCanvasElement;
        const data = c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data;
        let n = 0;
        for (let i = 3; i < data.length; i += 4) if (data[i] > 40) n++;
        return n / (c.width * c.height);
      });
    // a dense field: a real share of the canvas is drawn, not a blank or stub
    // frame (the renderer is marked before its first frame, so wait for one)
    await expect.poll(lit, { timeout: 5_000 }).toBeGreaterThan(0.02);
  });

  test("Auto on software graphics shows a still background: no canvas, nothing animating", async ({ page }) => {
    await page.goto("/");
    await expect(background(page)).toHaveAttribute("data-tier", "software");
    await expect(background(page)).toHaveAttribute("data-effect", "static");
    await expect(background(page).locator("canvas")).toHaveCount(0);
    await expect(page.getByTestId("static-background")).toBeVisible();
    expect(await animating(page)).toBe(false);
  });

  test("Auto without dedicated graphics runs GhostFibers, and it animates", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await page.addInitScript(() => {
      (window as unknown as { __RN_GPU__: string }).__RN_GPU__ = "integrated";
    });
    await page.goto("/");
    await expect(background(page)).toHaveAttribute("data-effect", "fibers");
    const fibers = page.getByTestId("ghost-fibers");
    await expect(fibers.locator("canvas")).toHaveCount(1);
    // laptop-safe: never drawn above 1x, whatever the screen's pixel density
    const ratio = await fibers.locator("canvas").evaluate((c: HTMLCanvasElement) => c.width / c.getBoundingClientRect().width);
    expect(ratio).toBeLessThanOrEqual(1.01);
    expect(await animating(page)).toBe(true);
    expect(errors).toEqual([]);
  });

  test("changing the setting switches the one background in place", async ({ page }) => {
    await page.goto("/sign-in");
    await page.getByRole("textbox", { name: "Email" }).fill("playwright@researchnexus.dev");
    await page.getByRole("textbox", { name: "Password" }).fill("anything");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(/\/home$/);
    await page.goto("/settings");
    const group = page.getByRole("group", { name: "Background" });
    await expect(page.getByText("Auto: this browser draws in software, so a still background.")).toBeVisible({ timeout: 10_000 });

    await group.getByRole("button", { name: "Animated" }).click();
    await expect(background(page)).toHaveAttribute("data-effect", "neural");
    await expect(background(page).locator("canvas")).toHaveCount(1);
    await group.getByRole("button", { name: "Static" }).click();
    await expect(background(page)).toHaveAttribute("data-effect", "static");
    await expect(background(page).locator("canvas")).toHaveCount(0);
    await group.getByRole("button", { name: "Auto" }).click();
    await expect(background(page)).toHaveAttribute("data-choice", "auto");
    await page.reload();
    await expect(group.getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
  });
});
