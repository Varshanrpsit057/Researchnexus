// spec: signing up, signing in with the emailed code, resetting a password,
// and signing out (production readiness, 2026-10-09).
//
// Everything is the real backend: the codes are read from the development
// server's mailbox (tests/auth-helpers.ts) exactly as a person reads them
// from their inbox. Each test runs in its own fresh browser context, so none
// of this touches the session the other specs share.
import { test, expect, type Page } from "@playwright/test";
import { API, justBefore, latestCode, signInViaApi, TEST_EMAIL, TEST_PASSWORD } from "../auth-helpers";

const unique = (tag: string) => `pw-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e4)}@researchnexus.dev`;

async function enterCode(page: Page, code: string) {
  await page.getByRole("textbox", { name: "Code" }).fill(code);
}

test.describe("Signing up, in and out", () => {
  test("sign-in and sign-up are separate pages that link to each other", async ({ page }) => {
    await page.goto("/sign-in");
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("Sign in to ResearchNexus");
    await expect(page.getByRole("textbox", { name: "Name" })).toHaveCount(0);
    await page.getByRole("link", { name: "Create an account" }).click();
    await page.waitForURL(/\/sign-up$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("Create your account");
    await expect(page.getByRole("textbox", { name: "Confirm password" })).toBeVisible();
    await page.getByRole("link", { name: "Sign in" }).click();
    await page.waitForURL(/\/sign-in$/);
  });

  test("a new account: the form checks itself, the emailed code confirms it, and it lands signed in", async ({ page }) => {
    const email = unique("signup");
    await page.goto("/sign-up");
    // nothing filled in: each field says what it needs
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Enter your name.")).toBeVisible();
    await expect(page.getByText("Enter your email address.")).toBeVisible();

    await page.getByRole("textbox", { name: "Name" }).fill("Grace Hopper");
    await page.getByRole("textbox", { name: "Email" }).fill(email);
    const password = page.getByRole("textbox", { name: "Password", exact: true });
    await password.fill("short");
    const rules = page.getByRole("list", { name: "Password rules" });
    await expect(rules.getByText("At least 10 characters")).toContainText("(not yet)");
    await password.fill(TEST_PASSWORD);
    await expect(rules.getByText("At least 10 characters")).toContainText("(met)");
    // show/hide
    await page.getByRole("button", { name: "Show password" }).click();
    await expect(password).toHaveAttribute("type", "text");
    await page.getByRole("button", { name: "Hide password" }).click();
    await expect(password).toHaveAttribute("type", "password");
    await page.getByRole("textbox", { name: "Confirm password" }).fill("Something-else-1");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("The two passwords don't match.")).toBeVisible();
    await page.getByRole("textbox", { name: "Confirm password" }).fill(TEST_PASSWORD);

    const since = justBefore();
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("Confirm your email");
    // no session yet: only the code makes one
    expect((await page.request.get(`${API}/api/v1/auth/session`)).ok()).toBe(true);
    expect((await (await page.request.get(`${API}/api/v1/auth/session`)).json()).user).toBeNull();

    await enterCode(page, "000000");
    await expect(page.getByText(/That code isn't right\. 4 tries left\./)).toBeVisible();
    await enterCode(page, await latestCode(page.request, email, since));
    await page.waitForURL(/\/home$/);
    await expect(page.getByRole("heading", { level: 1, name: "Welcome, Grace." })).toBeVisible();
  });

  test("signing in takes the password, then the emailed code; the session survives a reload; signing out ends it", async ({ page }) => {
    // the shared account exists with its password (made or claimed on first use)
    await signInViaApi(page.request);
    await page.context().clearCookies();

    await page.goto("/workspaces");
    await page.waitForURL(/\/sign-in\?next=%2Fworkspaces/);

    await page.getByRole("textbox", { name: "Email" }).fill(TEST_EMAIL);
    await page.getByRole("textbox", { name: "Password" }).fill("Not-the-password-1");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "That email and password don't match an account." })).toBeVisible();

    await page.getByRole("textbox", { name: "Password" }).fill(TEST_PASSWORD);
    const since = justBefore();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("Check your email");
    await expect(page.getByRole("button", { name: /Send a new code in \d+ s/ })).toBeDisabled();
    await enterCode(page, await latestCode(page.request, TEST_EMAIL, since));
    // back where sign-in was asked for
    await page.waitForURL(/\/workspaces$/);

    // the session is an httpOnly cookie: page scripts can't read it
    expect(await page.evaluate(() => document.cookie)).not.toContain("rn_session");
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Workspaces" })).toBeVisible();

    await page.getByRole("button", { name: /^Sign out/ }).click();
    await page.waitForURL(/\/sign-in$/);
    await page.goto("/home");
    await page.waitForURL(/\/sign-in\?next=%2Fhome/);
  });

  test("a forgotten password is reset with an emailed code, signing in and retiring the old password", async ({ page, browser }) => {
    const email = unique("reset");
    const owner = await browser.newContext();
    await signInViaApi(owner.request, email, TEST_PASSWORD, "Reset Reader");
    await owner.close();

    await page.goto("/sign-in");
    await page.getByRole("textbox", { name: "Email" }).fill(email);
    await page.getByRole("link", { name: "Forgot password?" }).click();
    await page.waitForURL(/\/forgot-password$/);
    // the email comes along (never in the address bar)
    await expect(page.getByRole("textbox", { name: "Email" })).toHaveValue(email);
    const since = justBefore();
    await page.getByRole("button", { name: "Send a code" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("Choose a new password");
    await page.getByRole("textbox", { name: "New password", exact: true }).fill("Brand-new-tide-7");
    await page.getByRole("textbox", { name: "Confirm new password" }).fill("Brand-new-tide-7");
    await enterCode(page, await latestCode(page.request, email, since));
    await page.getByRole("button", { name: "Reset password and sign in" }).click();
    await page.waitForURL(/\/home$/);

    const old = await page.request.post(`${API}/api/v1/auth/login`, { data: { email, password: TEST_PASSWORD } });
    expect(old.status()).toBe(401);
  });

  test("sign-in never sends the reader to another site afterwards", async ({ page }) => {
    await signInViaApi(page.request);
    await page.goto("/sign-in?next=https://evil.example/");
    await page.waitForURL(/\/home$/);
  });
});
