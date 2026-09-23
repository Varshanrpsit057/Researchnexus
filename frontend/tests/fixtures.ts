import { test as base, expect } from "@playwright/test";

/**
 * The seed every scenario (other than the sign-in flow itself) builds on:
 * a real sign-in against the dev backend (any email/password is accepted --
 * see sign-in/page.tsx), landing on /home, then straight to /papers since
 * every existing scenario's own steps start from there.
 */
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.goto("/sign-in");
    await page.getByRole("textbox", { name: "Email" }).fill("playwright@researchnexus.dev");
    await page.getByRole("textbox", { name: "Password" }).fill("anything");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(/\/home$/);
    await page.goto("/papers");
    await use(page);
  },
});

export { expect };
