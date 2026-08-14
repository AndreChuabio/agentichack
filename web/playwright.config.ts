import { defineConfig, devices } from "@playwright/test";

/**
 * Smoke-test config. Runs against `next dev` with placeholder Supabase env
 * vars -- no live Supabase project is required. Unauthenticated requests to
 * Supabase resolve to a null user rather than throwing, so auth-gated pages
 * correctly redirect to /login without a real backend.
 *
 * The port is overridable because `reuseExistingServer` will happily adopt
 * whatever is already listening. On a machine running another Next project on
 * 3000, the entire suite silently runs against that app: every assertion about
 * Merit's copy fails and any assertion loose enough to pass on a stranger's
 * 404 page passes. Set PLAYWRIGHT_PORT to something unused, and see
 * e2e/harness.spec.ts, which fails loudly if the server under test is not Merit.
 */
const PORT = process.env.PLAYWRIGHT_PORT ?? "3000";
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Opt-in override for sandboxes with a pre-installed browser at a
        // fixed path (unset in CI, which runs `playwright install` instead).
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
          : undefined,
      },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: {
      NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:9999",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "test-anon-key",
      NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:9998",
    },
  },
});
