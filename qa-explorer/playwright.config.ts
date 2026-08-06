import { defineConfig, devices } from "@playwright/test";

/**
 * Standalone live-site explorer config. NO webServer block -- this points at
 * production (https://meritai.me) rather than a local `next dev`. Video is
 * always on and trace is captured on every run so each wall an anonymous
 * visitor meets is filmed, not just asserted.
 */
const BASE_URL = process.env.EXPLORER_BASE_URL ?? "https://meritai.me";

export default defineConfig({
  testDir: "./personas",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "results/report.json" }]],
  outputDir: "results/artifacts",
  timeout: 60_000,
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1280, height: 720 },
    video: { mode: "on", size: { width: 1280, height: 720 } },
    trace: "on",
    screenshot: "off",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 720 },
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
          : undefined,
      },
    },
  ],
});
