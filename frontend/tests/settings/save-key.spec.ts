// spec: saving an LLM provider key.
//
// A backend crash (e.g. a missing RESEARCHNEXUS_KEY_VAULT_SECRET) answers
// without CORS headers, so the browser only sees a failed fetch -- the same
// thing an unreachable server looks like. That must not be reported as a
// problem with the key the user typed. The key below is a fake test value.
import { test, expect } from "../fixtures";

test.describe("Settings", () => {
  test("a save that never reaches the server says so instead of blaming the key", async ({ page }) => {
    await page.route("**/api/v1/settings/llm-keys", (route) =>
      route.request().method() === "PUT" ? route.abort("failed") : route.fallback()
    );

    await page.goto("/settings");
    await page.getByLabel("API key").fill("sk-test-not-a-real-key");
    await page.getByRole("button", { name: "Save key" }).click();

    await expect(page.getByText("Couldn't reach the server to save this key", { exact: false })).toBeVisible();
    await expect(page.getByText("Check the value", { exact: false })).toHaveCount(0);
    // the typed key is kept so the user can simply retry
    await expect(page.getByLabel("API key")).toHaveValue("sk-test-not-a-real-key");
  });
});
