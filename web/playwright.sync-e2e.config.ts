import { defineConfig } from "@playwright/test";

// The cross-client sync suite (roadmap P5-09) against a real server: scripts/sync-e2e.sh
// starts the API, the vault watcher and the web app, and builds the Apple engine's
// `opennote-sync` command; this config only points Playwright at them.
const executablePath = process.env.OPENNOTE_PW_EXECUTABLE;

export default defineConfig({
  testDir: "tests/sync-e2e",
  reporter: "list",
  forbidOnly: !!process.env.CI,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  use: {
    browserName: "chromium",
    baseURL: process.env.OPENNOTE_E2E_WEB ?? "http://127.0.0.1:5173",
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
});
