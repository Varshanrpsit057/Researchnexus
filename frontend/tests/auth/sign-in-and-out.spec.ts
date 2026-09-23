// spec: manual (single well-known critical flow; see Phase 15 completion report)
import { test, expect } from "@playwright/test";

test.describe("Signing in and out", () => {
  test("should sign in, survive a hard reload, and sign out", async ({ page }) => {
    // 1. Navigate to the sign-in page
    await page.goto("/sign-in");

    // 2. Fill in any email and password (dev auth accepts anything)
    await page.getByRole("textbox", { name: "Email" }).fill("playwright@researchnexus.dev");
    await page.getByRole("textbox", { name: "Password" }).fill("anything");

    // 3. Submit the sign-in form
    await page.getByRole("button", { name: "Sign in" }).click();

    // 4. Land on the authenticated research home
    await expect(page).toHaveURL(/\/home$/);
    await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();

    // 5. A hard reload of an authenticated page must not bounce back to
    //    /sign-in -- regression test for the render-phase redirect race
    //    (AppShell calling router.replace during render, compounded by an
    //    auth snapshot that briefly read "no token" on every fresh
    //    navigation) found and fixed this phase.
    await page.reload();
    await expect(page).toHaveURL(/\/home$/);
    await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();

    // 6. Sign out returns to the sign-in page
    await page.getByRole("button", { name: /Sign out/ }).click();
    await expect(page).toHaveURL(/\/sign-in/);
  });
});
