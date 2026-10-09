import fs from "node:fs";
import path from "node:path";
import { test as base, expect } from "@playwright/test";
import { API, signInViaApi, TEST_EMAIL } from "./auth-helpers";

/**
 * The seed every scenario (other than the sign-in flows themselves) builds
 * on: signed in as the test account -- once per worker, through the real
 * flow (password, then the emailed code; see auth-helpers.ts), its session
 * cookie reused by every test the worker runs -- then on /papers, where
 * every existing scenario's own steps start.
 *
 * A test that signs out must do it in a context of its own: signing out
 * here would end the session the rest of the worker shares.
 */
export const test = base.extend<object, { workerStorageState: string }>({
  storageState: ({ workerStorageState }, use) => use(workerStorageState),
  workerStorageState: [
    async ({ browser }, use, workerInfo) => {
      // kept beside the test results (git-ignored) and reused while the session lasts
      const file = path.join(workerInfo.project.outputDir, "..", ".auth", `worker-${workerInfo.parallelIndex}.json`);
      fs.mkdirSync(path.dirname(file), { recursive: true });
      if (fs.existsSync(file)) {
        const saved = await browser.newContext({ storageState: file });
        const state = await saved.request.get(`${API}/api/v1/auth/session`);
        const live = state.ok() && (await state.json()).user?.email === TEST_EMAIL;
        await saved.close();
        if (live) {
          await use(file);
          return;
        }
      }
      const context = await browser.newContext({ storageState: undefined });
      await signInViaApi(context.request);
      await context.storageState({ path: file });
      await context.close();
      await use(file);
    },
    { scope: "worker" },
  ],
  page: async ({ page }, use) => {
    await page.goto("/papers");
    await use(page);
  },
});

export { expect };
