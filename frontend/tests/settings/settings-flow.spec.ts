// spec: Phase 14 (Settings) at /settings.
//
// The account, the keys list, choosing a default provider, removing a key,
// the provider in use, workspace caps and the service's health are all the
// real backend. Keys are stored through the real repository (seed-keys.py,
// encrypted with the server's own secret). The three calls that make the
// backend talk to a provider -- testing, saving and re-checking a key -- are
// answered at the network layer: tests never send a key to a real provider.
// Their answers are applied to the real rows the same way the server would.
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const PYTHON = String.raw`H:\Researchnexus\backend\.venv\Scripts\python.exe`;
const SEED = path.join(__dirname, "seed-keys.py");
const EMAIL = "playwright@researchnexus.dev";
const keys = (...args: string[]) => JSON.parse(execFileSync(PYTHON, [SEED, ...args]).toString());

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const provider = (page: Page, id: string) => page.getByTestId(`provider-${id}`);

test.describe("Settings", () => {
  test.beforeEach(() => keys("clear", EMAIL));
  test.afterEach(() => keys("clear", EMAIL)); // other specs rely on "no working key" being real

  test("account, keys and the provider in use, workspace caps, device preferences and service health", async ({ page }) => {
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    keys("set", EMAIL, "groq=working:wk01", "openai=failed:fl02");
    const consoleErrors = collectConsoleErrors(page);
    await page.getByRole("link", { name: "Settings" }).first().click();
    await page.waitForURL(/\/settings$/);
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

    // 1. account (real /me)
    await expect(page.locator("#account")).toContainText(EMAIL);
    await expect(page.locator("#account")).toContainText("Local sign-in: the email is the account.");
    await page.getByRole("button", { name: "Copy the account ID" }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^usr_/);

    // 2. keys, and which provider every model stage uses (real list + /me)
    const status = page.getByTestId("model-status");
    await expect(status).toHaveText(/use Groq, the first working key you saved\. Choose a default to decide\./);
    await expect(provider(page, "groq")).toContainText("Working");
    await expect(provider(page, "groq")).toContainText("•••• wk01");
    await expect(provider(page, "groq")).toContainText("in use");
    await expect(provider(page, "openai")).toContainText("Failed its last check");
    await expect(provider(page, "gemini")).toContainText("No key");
    // the full key is never on the page
    await expect(page.getByText(/sk-test-/)).toHaveCount(0);

    // choosing a default whose key fails: the page says what is used instead (real PATCH /me)
    await page.getByRole("button", { name: "Make OpenAI the default" }).click();
    await expect(status).toHaveText("Your default, OpenAI, has no working key right now, so Groq is used instead.");
    await page.getByRole("button", { name: "Make Groq the default" }).click();
    await expect(status).toHaveText("Chat, comparison, gap finding and directions use Groq, your default.");
    await page.reload();
    await expect(page.getByRole("button", { name: "Groq is your default; clear it" })).toHaveAttribute("aria-pressed", "true");

    // re-checking a stored key (the provider's answer, applied as the server would)
    await page.route("**/api/v1/settings/llm-keys/openai/check", async (route) => {
      const stored = keys("set", EMAIL, "openai=working:fl02");
      await route.fulfill({
        json: {
          key: { ...stored.find((k: { provider: string }) => k.provider === "openai"), checked_at: new Date().toISOString() },
          result: { success: true, latency_ms: 350, capabilities: { json_mode: true, context_tokens: 128000, streaming: true } },
        },
      });
    });
    await page.getByRole("button", { name: "Check the OpenAI key again" }).click();
    await expect(provider(page, "openai")).toContainText("Checked just now. It works: answered in 350 ms, JSON mode, a 128,000-token context, streaming.");
    await expect(provider(page, "openai")).toContainText("Working");

    // removing a key asks first, then really removes it (real DELETE)
    await page.getByRole("button", { name: "Remove the OpenAI key" }).click();
    await provider(page, "openai").getByRole("button", { name: "Remove", exact: true }).click();
    await expect(provider(page, "openai")).toContainText("No key");
    expect(keys("set", EMAIL).map((k: { provider: string }) => k.provider)).toEqual(["groq"]);

    // 3. adding a key: tested without saving, then saved; the input is cleared after
    await page.route("**/api/v1/settings/llm-keys/test", (route) =>
      route.fulfill({ json: { success: true, latency_ms: 420, capabilities: { json_mode: true, context_tokens: 1048576, streaming: true } } }),
    );
    await page.route("**/api/v1/settings/llm-keys", async (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      const stored = keys("set", EMAIL, "gemini=working:gm03");
      await route.fulfill({ json: { ...stored.find((k: { provider: string }) => k.provider === "gemini") } });
    });
    await provider(page, "gemini").getByRole("button", { name: "Add a Gemini key" }).click();
    const input = page.getByLabel("API key");
    await expect(input).toBeFocused();
    await expect(page.getByRole("combobox", { name: "Provider" })).toHaveValue("gemini");
    await expect(input).toHaveAttribute("type", "password");
    await input.fill("sk-test-not-a-real-key-gm03");
    await page.getByRole("button", { name: "Show the key" }).click();
    await expect(input).toHaveAttribute("type", "text");
    await page.getByRole("button", { name: "Test without saving" }).click();
    await expect(page.getByText("It works: answered in 420 ms, JSON mode, a 1,048,576-token context, streaming. Not saved yet.")).toBeVisible();
    await page.getByRole("button", { name: "Save key" }).click();
    await expect(page.getByText("Saved. The Gemini key works, and it is stored encrypted.")).toBeVisible();
    await expect(input).toHaveValue("");
    await expect(input).toHaveAttribute("type", "password");
    await expect(provider(page, "gemini")).toContainText("•••• gm03");

    // 4. a workspace's cap: only a positive amount is accepted, and it is saved (real PATCH)
    const firstWorkspace = page.getByRole("list", { name: "Workspaces" }).getByRole("listitem").first();
    const cap = firstWorkspace.getByLabel("Spending cap (USD)");
    const originalCap = await cap.inputValue();
    await cap.fill("0");
    await expect(cap).toHaveAttribute("aria-invalid", "true");
    await expect(firstWorkspace.getByRole("button", { name: "Save" })).toBeDisabled();
    await cap.fill("7.50");
    await firstWorkspace.getByRole("button", { name: "Save" }).click();
    await expect(firstWorkspace.getByText("Saved.")).toBeVisible();
    const workspaceHref = await firstWorkspace.getByRole("link", { name: "Open workspace" }).getAttribute("href");
    await page.reload();
    await expect(page.getByRole("list", { name: "Workspaces" }).getByRole("listitem").first().getByLabel("Spending cap (USD)")).toHaveValue("7.50");

    // 5. this device: a still background, and the reference style the citations page opens in
    await page.getByRole("group", { name: "Background" }).getByRole("button", { name: "Still" }).click();
    await expect(page.getByRole("group", { name: "Background" }).getByRole("button", { name: "Still" })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("group", { name: "Reference style" }).getByRole("button", { name: "IEEE" }).click();
    expect(await page.evaluate(() => localStorage.getItem("researchnexus.pref.referenceStyle"))).toBe("ieee");
    await page.goto(`${workspaceHref}/citations`);
    await expect(page.getByRole("group", { name: "Reference style" }).first().getByRole("button", { name: "IEEE" })).toHaveAttribute("aria-pressed", "true", {
      timeout: 10_000,
    });
    await page.goto("/settings");
    // leave the workspace and this device as they were
    const restore = page.getByRole("list", { name: "Workspaces" }).getByRole("listitem").first();
    if (originalCap !== "7.50") {
      await restore.getByLabel("Spending cap (USD)").fill(originalCap);
      await restore.getByRole("button", { name: "Save" }).click();
      await expect(restore.getByText("Saved.")).toBeVisible();
    }
    await page.getByRole("group", { name: "Background" }).getByRole("button", { name: "Moving" }).click();
    await page.getByRole("group", { name: "Reference style" }).getByRole("button", { name: "APA" }).click();

    // 6. the service (real /health)
    await expect(page.getByTestId("service-status")).toContainText("http://localhost:8000");
    await expect(page.getByTestId("service-status")).toContainText("Connected · database ok");

    // 7. signing out
    await page.locator("#account").getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL(/\/sign-in/);
    expect(consoleErrors).toEqual([]);
  });

  test("a server that can't be reached is said plainly", async ({ page }) => {
    await page.route("**/health", (route) => route.abort("failed"));
    await page.goto("/settings");
    await expect(page.getByTestId("service-status")).toContainText("Can't reach the server at http://localhost:8000.", { timeout: 10_000 });
    await expect(page.getByTestId("model-status")).toContainText("No working key is saved"); // real: none saved
  });
});
