// spec: Phase 14 (Settings) at /settings.
//
// The account, the keys list, choosing a default provider, removing a key,
// the provider in use, model usage, renaming a workspace and the service's
// health are all the real backend. Usage comes from the real ledger
// (seed-usage.py records calls through the real metering path with a
// scripted model). Keys are stored through the real repository (seed-keys.py,
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
const usage = (...args: string[]) => JSON.parse(execFileSync(PYTHON, [path.join(__dirname, "seed-usage.py"), ...args]).toString());

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

const provider = (page: Page, id: string) => page.getByTestId(`provider-${id}`);
// each section is its own pane, opened from the sidebar (2026-10-06)
const open = (page: Page, name: string | RegExp) =>
  page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name }).click();

test.describe("Settings", () => {
  test.beforeEach(() => {
    keys("clear", EMAIL);
    usage("clear", EMAIL);
  });
  test.afterEach(() => {
    keys("clear", EMAIL); // other specs rely on "no working key" being real
    usage("clear", EMAIL);
  });

  test("account, keys and the provider in use, model usage, workspaces, device preferences and service health", async ({ page }) => {
    test.setTimeout(90_000); // one walk through every section, two ledger seeds and a workspace visit
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    keys("set", EMAIL, "groq=working:wk01", "openai=failed:fl02");
    const consoleErrors = collectConsoleErrors(page);
    await page.getByRole("link", { name: "Settings" }).first().click();
    await page.waitForURL(/\/settings$/);
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

    // 1. account (real /me)
    await expect(page.locator("#account")).toContainText(EMAIL);
    await expect(page.locator("#account")).toContainText("Your password, then a one-time code sent to your email.");
    await expect(page.locator("#account").getByText("Verified")).toBeVisible();
    // this browser is listed among the signed-in devices
    await expect(page.getByRole("region", { name: "Signed-in devices" }).getByText("This device")).toBeVisible();
    await page.getByRole("button", { name: "Copy the account ID" }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^usr_/);

    // 2. keys, and which provider every model stage uses (real list + /me)
    await open(page, /^Language models/);
    await expect(page.getByRole("link", { name: /^Language models/ })).toHaveAttribute("aria-current", "page");
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

    // 4. model usage: the providers' own token counts from the real ledger, over a stated range -- and no cost
    await open(page, "Model usage");
    await expect(page.getByTestId("usage-summary")).toHaveText("No model calls in the last 30 days.");
    const seeded = usage("seed", EMAIL) as { workspace_id: string; title: string };
    await page.reload();
    const panel = page.getByTestId("usage");
    const summary = page.getByTestId("usage-summary");
    const row = (name: string | RegExp) => panel.getByRole("row", { name });
    await expect(summary).toContainText(/^11,300 tokens across 5 calls · Last 30 days, since /);
    await expect(row(/^Research gaps/)).toContainText("5,800");
    await expect(row(/^Research gaps/)).toContainText("200 reasoning");
    await expect(row(/^Chat/)).toContainText("3,000");
    await expect(row(/^Chat/)).toContainText("800 cached");
    await expect(row(/^Chat/)).toContainText("1 failed");
    await expect(row(/^Paper profiles/)).toContainText("2,500");
    await expect(row(/^All/)).toContainText("11,300");
    await expect(panel).toContainText("1 call failed and reported no tokens; it is counted as calls only.");
    // the range reaches the backend: the call from 45 days ago joins for all time
    await panel.getByRole("group", { name: "Range" }).getByRole("button", { name: "All time" }).click();
    await expect(summary).toContainText(/^22,300 tokens across 6 calls · All time, since /);
    await expect(row(/^Chat/)).toContainText("14,000");
    await panel.getByRole("group", { name: "Group" }).getByRole("button", { name: "By model" }).click();
    await expect(row(/^DeepSeek deepseek-flash/)).toContainText("19,800");
    await expect(row(/^Gemini gemini-2\.5-flash/)).toContainText("2,500");
    await panel.getByRole("group", { name: "Group" }).getByRole("button", { name: "By workspace" }).click();
    await expect(row(/^Outside a workspace/)).toContainText("2,500");
    await expect(panel.getByRole("link", { name: seeded.title })).toHaveAttribute("href", `/workspace/${seeded.workspace_id}`);
    // no price is known, so none is shown: the bill is the provider's
    await expect(page.getByTestId("usage-cost-note")).toContainText("No cost is shown.");
    await expect(page.getByTestId("usage-cost-note").getByRole("link", { name: /DeepSeek/ })).toHaveAttribute("href", "https://platform.deepseek.com");
    await expect(page.getByTestId("usage-cost-note").getByRole("link", { name: /Gemini/ })).toHaveAttribute("href", "https://aistudio.google.com");
    expect(await page.locator("main").innerText()).not.toContain("$");

    // the workspace's own overview shows its share, from the same ledger
    await page.goto(`/workspace/${seeded.workspace_id}`);
    await expect(page.getByTestId("workspace-usage")).toContainText("8,800 tokens in the last 30 days");
    await expect(page.getByTestId("workspace-usage")).toContainText("Research gaps 5,800 · Chat 3,000");
    await page.goto("/settings");

    // 5. a workspace's name is saved (real PATCH); there is no spending cap any more
    await open(page, "Library & workspaces");
    const firstWorkspace = page.getByRole("list", { name: "Workspaces" }).getByRole("listitem").first();
    await expect(firstWorkspace.getByLabel("Spending cap (USD)")).toHaveCount(0);
    const name = firstWorkspace.getByLabel("Name", { exact: true });
    const originalName = await name.inputValue();
    await name.fill(`${originalName} (renamed)`);
    await firstWorkspace.getByRole("button", { name: "Save" }).click();
    await expect(firstWorkspace.getByText("Saved.")).toBeVisible();
    const workspaceHref = await firstWorkspace.getByRole("link", { name: "Open workspace" }).getAttribute("href");
    await page.reload();
    await expect(page.getByRole("list", { name: "Workspaces" }).getByRole("listitem").first().getByLabel("Name", { exact: true })).toHaveValue(`${originalName} (renamed)`);

    // 6. this device: a still background, and the reference style the citations page opens in
    await open(page, "Appearance");
    await page.getByRole("group", { name: "Background" }).getByRole("button", { name: "Static" }).click();
    await expect(page.getByRole("group", { name: "Background" }).getByRole("button", { name: "Static" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("background")).toHaveAttribute("data-effect", "static");
    await page.getByRole("group", { name: "Reference style" }).getByRole("button", { name: "IEEE" }).click();
    expect(await page.evaluate(() => localStorage.getItem("researchnexus.pref.referenceStyle"))).toBe("ieee");
    await page.goto(`${workspaceHref}/citations`);
    await expect(page.getByRole("group", { name: "Reference style" }).first().getByRole("button", { name: "IEEE" })).toHaveAttribute("aria-pressed", "true", {
      timeout: 10_000,
    });
    await page.goto("/settings#library");
    // leave the workspace and this device as they were
    const restore = page.getByRole("list", { name: "Workspaces" }).getByRole("listitem").first();
    await restore.getByLabel("Name", { exact: true }).fill(originalName);
    await restore.getByRole("button", { name: "Save" }).click();
    await expect(restore.getByText("Saved.")).toBeVisible();
    await open(page, "Appearance");
    await page.getByRole("group", { name: "Background" }).getByRole("button", { name: "Auto" }).click();
    await page.getByRole("group", { name: "Reference style" }).getByRole("button", { name: "APA" }).click();

    // 7. the service (real /health)
    await open(page, "Service & about");
    await expect(page.getByTestId("service-status")).toContainText("http://localhost:8000");
    await expect(page.getByTestId("service-status")).toContainText("Connected · database ok");

    // 8. signing out is offered (signing out for real is tests/auth: this session is shared)
    await open(page, "Account");
    await expect(page.locator("#account").getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
    expect(consoleErrors).toEqual([]);
  });

  test("a server that can't be reached is said plainly", async ({ page }) => {
    await page.route("**/health", (route) => route.abort("failed"));
    await page.goto("/settings#service");
    await expect(page.getByTestId("service-status")).toContainText("Can't reach the server at http://localhost:8000.", { timeout: 10_000 });
    await open(page, /^Language models/);
    await expect(page.getByTestId("model-status")).toContainText("No working key is saved"); // real: none saved
  });
});
