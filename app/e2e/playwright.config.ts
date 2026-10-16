import { defineConfig } from "@playwright/test";

/** Started by e2e/run.mjs, which provides the engine + Vite and the E2E_* env. */
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:1420",
    viewport: { width: 1440, height: 900 },
    launchOptions: { executablePath: process.env.CHROMIUM_PATH ?? "/usr/bin/chromium" },
    screenshot: "only-on-failure",
  },
});
