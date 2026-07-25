import { test, expect, type Page } from "@playwright/test";

/**
 * Regression gate: every route must render without crashing before a merge
 * lands. Runs against placeholder Supabase env (see playwright.config.ts),
 * so there is never an authenticated session -- public pages must render
 * their signed-out content, and every (app) route must redirect to /login.
 */

/** Fails the test if the page threw an uncaught error or logged one to the console. */
function failOnPageErrors(page: Page) {
  page.on("pageerror", (err) => {
    throw new Error(`Uncaught page error: ${err.message}`);
  });
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      throw new Error(`Console error: ${msg.text()}`);
    }
  });
}

const PUBLIC_PAGES: Array<{ path: string; expectText: string | RegExp }> = [
  { path: "/", expectText: "Extraordinary ability, evidenced" },
  { path: "/login", expectText: "Welcome back" },
  { path: "/signup", expectText: "Create your account" },
  { path: "/privacy", expectText: /privacy/i },
  { path: "/forgot-password", expectText: "Reset your password" },
  { path: "/reset-password", expectText: "Verifying your reset link" },
];

for (const { path, expectText } of PUBLIC_PAGES) {
  test(`${path} renders without crashing`, async ({ page }) => {
    failOnPageErrors(page);
    const response = await page.goto(path, { waitUntil: "networkidle" });
    expect(response?.ok()).toBeTruthy();
    await expect(page.getByText(expectText).first()).toBeVisible();
  });
}

const AUTH_GATED_PAGES = ["/productize", "/track", "/market", "/cfp"];

for (const path of AUTH_GATED_PAGES) {
  test(`${path} redirects unauthenticated visitors to /login`, async ({
    page,
  }) => {
    failOnPageErrors(page);
    const response = await page.goto(path, { waitUntil: "networkidle" });
    expect(response?.ok()).toBeTruthy();
    await expect(page).toHaveURL(/\/login(\?|$)/);
    await expect(page.getByText("Welcome back")).toBeVisible();
  });
}
