import { expect, test } from "@playwright/test";

/**
 * The publish wizard lives under app/(app), whose layout redirects visitors
 * without a Supabase session to /login. This harness runs against placeholder
 * Supabase env (see playwright.config.ts) so there is never a session, which
 * is why this asserts the route exists and is gated rather than asserting the
 * signed-in wizard body -- the same posture every (app) route takes in
 * smoke.spec.ts.
 */
test("publish route exists and is gated behind sign-in", async ({ page }) => {
  page.on("pageerror", (err) => {
    throw new Error(`Uncaught page error: ${err.message}`);
  });

  const response = await page.goto("/publish", { waitUntil: "networkidle" });
  expect(response?.ok()).toBeTruthy();
  await expect(page).toHaveURL(/\/login(\?|$)/);
  await expect(page.getByText("Welcome back")).toBeVisible();
});
