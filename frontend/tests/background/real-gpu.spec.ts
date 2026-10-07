// spec: Auto on this machine's real graphics (remediation Phase 14).
//
// Chromium is launched on the real GPU (Direct3D 11 through ANGLE) instead of
// Playwright's default software renderer. On a machine whose browser reports
// a dedicated GPU, Auto must choose the neural network; on any other machine
// the test is skipped rather than pretending (the software and integrated
// paths are covered in constellation.spec.ts).
import { test, expect } from "@playwright/test";

test.use({ launchOptions: { args: ["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=d3d11"] } });

test("Auto with a dedicated GPU runs the neural network", async ({ page }) => {
  await page.goto("/");
  const background = page.getByTestId("background");
  await expect(background).not.toHaveAttribute("data-tier", "pending");
  const tier = await background.getAttribute("data-tier");
  test.skip(tier !== "dedicated", `this machine's browser reports ${tier} graphics`);
  await expect(background).toHaveAttribute("data-effect", "neural");
  await expect(page.locator("canvas[data-renderer]")).toHaveAttribute("data-renderer", "webgl2");
  const clip = { x: 0, y: 500, width: 1200, height: 200 };
  const a = await page.screenshot({ clip });
  await page.waitForTimeout(700);
  expect((await page.screenshot({ clip })).equals(a)).toBe(false);
});
