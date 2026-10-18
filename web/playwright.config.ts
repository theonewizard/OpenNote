import { defineConfig } from "@playwright/test";

// CI uses the Chromium build that matches @playwright/test. Set
// OPENNOTE_PW_EXECUTABLE only where that build cannot be installed.
const executablePath = process.env.OPENNOTE_PW_EXECUTABLE;

export default defineConfig({
  testDir: "tests/e2e",
  reporter: "list",
  // A test.only left in a commit fails CI instead of skipping every other test.
  forbidOnly: !!process.env.CI,
  use: {
    browserName: "chromium",
    baseURL: "http://127.0.0.1:4173",
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  webServer: {
    command:
      "npm run build && npm run preview -- --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
  },
});
