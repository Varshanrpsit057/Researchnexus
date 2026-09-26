import { defineConfig, devices } from "@playwright/test";

/**
 * Assumes the backend (uvicorn app.main:app, port 8000) is already running
 * separately -- Playwright's webServer only manages the frontend dev
 * server here, matching this phase's "no deployment yet" scope. The dev
 * auth backend accepts any email/password, so no seeded credentials are
 * needed; tests that read/write data use whatever the shared dev database
 * already has plus what they create themselves.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    // the project's one frontend port (the backend is always :8000)
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
