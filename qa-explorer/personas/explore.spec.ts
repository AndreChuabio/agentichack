import { test } from "@playwright/test";
import {
  ErrorChannel,
  didNavigate,
  errorBannerVisible,
  expect,
  recordCheckpoint,
} from "./wall-detector";

/**
 * Browse-only persona explorer against the LIVE MeritAI site.
 *
 * SAFETY RAIL: the explorer is an anonymous visitor. It never submits the
 * signup/login/reset forms, never types an email/password/card, and never
 * completes any Stripe checkout. At each auth/payment/recovery gate it STOPS,
 * films the wall (money-shot + video + action-log), and asserts inspect-only
 * facts about the form -- it does not cross the gate.
 */

// --- Persona 1: Newcomer clicks the primary CTA to start a case ------------
test("persona-1 newcomer: land, read value prop, click Start your case", async ({
  page,
}) => {
  const errs = new ErrorChannel(page);

  const landing = await page.goto("/", { waitUntil: "networkidle" });
  expect(landing?.status(), "landing HTTP status").toBeLessThan(400);
  // Value prop must render for a true anonymous visitor.
  await expect(page.getByText("Extraordinary ability, evidenced")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /O-1A case/i }),
  ).toBeVisible();
  await recordCheckpoint(page, errs, {
    persona: "persona-1-newcomer",
    step: "1-landing-value-prop",
    wall_type: "none",
    note: "Anonymous landing renders full pitch.",
  });

  // Click the primary CTA. Expect navigation to the signup gate.
  const cta = page.getByRole("button", { name: "Start your case" });
  await expect(cta).toBeVisible();
  const nav = await didNavigate(page, async () => {
    await cta.click();
  });
  expect(nav.changed, "Start your case should navigate somewhere").toBeTruthy();
  await page.waitForURL(/\/signup(\?|$)/, { timeout: 15_000 });

  // WALL: signup form. Inspect only -- DO NOT submit.
  await expect(page.getByText("Create your account")).toBeVisible();
  const emailField = page.locator('input[name="email"]');
  const pwField = page.locator('input[name="password"]');
  const submit = page.getByRole("button", { name: /Create account/i });
  await expect(emailField).toBeVisible();
  await expect(pwField).toBeVisible();
  await expect(submit).toBeVisible();
  await recordCheckpoint(page, errs, {
    persona: "persona-1-newcomer",
    step: "2-signup-wall",
    wall_type: "auth-gate",
    note: "Primary CTA -> /signup email+password form. STOP: not submitted.",
  });
});

// --- Persona 2: Returning visitor tries to sign in -------------------------
test("persona-2 returning: land, click Sign in, reach login wall", async ({
  page,
}) => {
  const errs = new ErrorChannel(page);
  await page.goto("/", { waitUntil: "networkidle" });

  const signIn = page.getByRole("button", { name: "Sign in" });
  await expect(signIn).toBeVisible();
  const nav = await didNavigate(page, async () => {
    await signIn.click();
  });
  expect(nav.changed, "Sign in should navigate").toBeTruthy();
  await page.waitForURL(/\/login(\?|$)/, { timeout: 15_000 });

  // WALL: login form. Inspect only.
  await expect(page.getByText("Welcome back")).toBeVisible();
  await expect(page.locator('input[name="email"]')).toBeVisible();
  await expect(page.locator('input[name="password"]')).toBeVisible();
  await recordCheckpoint(page, errs, {
    persona: "persona-2-returning",
    step: "1-login-wall",
    wall_type: "auth-gate",
    note: "Sign in -> /login form. STOP: not submitted.",
  });
});

// --- Persona 3: Locked-out user tries to recover access --------------------
test("persona-3 lockedout: forgot-password + reset-password states", async ({
  page,
}) => {
  const errs = new ErrorChannel(page);

  await page.goto("/login", { waitUntil: "networkidle" });
  const forgot = page.getByRole("link", { name: /Forgot your password/i });
  if (await forgot.count()) {
    await didNavigate(page, async () => {
      await forgot.first().click();
    });
    await page.waitForURL(/\/forgot-password(\?|$)/, { timeout: 15_000 }).catch(
      () => {},
    );
  } else {
    await page.goto("/forgot-password", { waitUntil: "networkidle" });
  }

  // WALL: password-reset REQUEST form. Filling+submitting would fire
  // supabase.auth.resetPasswordForEmail -- inspect only, DO NOT submit.
  await expect(
    page.getByRole("heading", { name: "Reset your password" }),
  ).toBeVisible();
  await expect(page.locator('input[name="email"]')).toBeVisible();
  await recordCheckpoint(page, errs, {
    persona: "persona-3-lockedout",
    step: "1-forgot-password-wall",
    wall_type: "recovery-gate",
    note: "Reset-request form. STOP: not submitted (would email a real reset).",
  });

  // /reset-password with no token: static verifying state, safe to view.
  await page.goto("/reset-password", { waitUntil: "networkidle" });
  await expect(page.getByText(/Verifying your reset link/i)).toBeVisible();
  await recordCheckpoint(page, errs, {
    persona: "persona-3-lockedout",
    step: "2-reset-password-no-token",
    wall_type: "none",
    note: "Static verifying state renders with no token. No submission.",
  });
});

// --- Persona 4: Deep-link jumper hits every product surface directly -------
const PRODUCT_SURFACES = ["/productize", "/track", "/market", "/cfp"];

test("persona-4 deeplink: product surfaces redirect to login (paywall probe)", async ({
  page,
}) => {
  const errs = new ErrorChannel(page);

  for (const surface of PRODUCT_SURFACES) {
    const resp = await page.goto(surface, { waitUntil: "networkidle" });
    expect(resp?.status(), `${surface} HTTP status`).toBeLessThan(400);
    // WALL: auth redirect. The Stripe paywall lives INSIDE /track post-login,
    // so it is structurally unreachable anonymously -- the auth gate is the
    // only wall a visitor meets. We record that the paywall is not exposed.
    await page.waitForURL(/\/login(\?|$)/, { timeout: 15_000 });
    await expect(page.getByText("Welcome back")).toBeVisible();
    await recordCheckpoint(page, errs, {
      persona: "persona-4-deeplink",
      step: `redirect-${surface.replace(/\//g, "")}`,
      wall_type: "auth-gate",
      note: `${surface} -> /login. No anonymous preview; paywall not exposed.`,
    });
  }
});

// --- Persona 5: Trust/privacy evaluator ------------------------------------
test("persona-5 evaluator: read the privacy policy end-to-end", async ({
  page,
}) => {
  const errs = new ErrorChannel(page);
  const resp = await page.goto("/privacy", { waitUntil: "networkidle" });
  expect(resp?.status(), "/privacy HTTP status").toBeLessThan(400);
  await expect(page.getByText(/privacy/i).first()).toBeVisible();

  const banner = await errorBannerVisible(page);
  await recordCheckpoint(page, errs, {
    persona: "persona-5-evaluator",
    step: "1-privacy-policy",
    wall_type: banner ? "error-banner" : "none",
    note: banner
      ? "Unexpected error banner on public privacy page."
      : "Public privacy policy fully readable; no wall (completeness check).",
  });
});
