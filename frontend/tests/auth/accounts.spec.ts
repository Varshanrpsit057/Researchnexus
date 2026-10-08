// spec: one account per email, whatever its case, and saying so (2026-10-07).
//
// Sign-in makes a new, empty account for an email it hasn't seen; a reader
// who typed a different address used to land in an empty app with no hint
// why. Everything here is the real backend.
import { test, expect } from "@playwright/test";

test.describe("Accounts on this browser", () => {
  test("a new email is said to be new, the browser offers it next time, and its capitals don't matter", async ({ page }) => {
    const email = `pw-new-${Date.now()}@researchnexus.dev`;

    // 1. A new email: the home page says a new account was made, and how a review goes
    await page.goto("/sign-in");
    await page.getByRole("textbox", { name: "Email" }).fill(email);
    await page.getByRole("textbox", { name: "Password" }).fill("anything");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(/\/home$/);
    await expect(page.getByRole("status").filter({ hasText: "A new account was made for" })).toContainText(email);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Welcome, pw-new-/);
    await expect(page.getByRole("heading", { name: "How a review goes" })).toBeVisible();
    // said once: a reload doesn't repeat it
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("A new account was made for")).toHaveCount(0);

    // 2. Signed out, the browser offers the account it used
    await page.getByRole("button", { name: "Sign out" }).first().click();
    await page.waitForURL(/\/sign-in/);
    const recent = page.getByRole("button", { name: email, exact: true });
    await expect(recent).toBeVisible();

    // an email not used here is flagged before it makes an account
    await page.getByRole("textbox", { name: "Email" }).fill("someone-else@researchnexus.dev");
    await expect(page.getByText("Not used in this browser before.", { exact: false })).toBeVisible();
    await recent.click();
    await expect(page.getByRole("textbox", { name: "Email" })).toHaveValue(email);
    await expect(page.getByText("Not used in this browser before.", { exact: false })).toHaveCount(0);

    // 3. The same email in capitals is the same account: no new-account notice
    await page.getByRole("textbox", { name: "Email" }).fill(email.toUpperCase());
    await page.getByRole("textbox", { name: "Password" }).fill("anything");
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(/\/home$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("A new account was made for")).toHaveCount(0);

    // 4. An account can be forgotten in this browser
    await page.getByRole("button", { name: "Sign out" }).first().click();
    await page.waitForURL(/\/sign-in/);
    await page.getByRole("button", { name: `Forget ${email} in this browser` }).click();
    await expect(page.getByRole("button", { name: email, exact: true })).toHaveCount(0);
  });
});
