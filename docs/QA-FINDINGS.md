# MeritAI QA Explorer — browse-only persona runs vs live site

**Target:** https://meritai.me (production) · **Backend:** paperpilot-api-production.up.railway.app
**Date:** 2026-08-05 · **Runner:** `qa-explorer/` (standalone Playwright, video-on, trace-on, 1280×720)
**Persona:** a single **anonymous visitor**. 5 personas, 11 checkpoints, 0 HTTP errors, 0 console errors.

## Safety rail (held — see confirmation at bottom)

The explorer never crossed an auth or payment wall. It did **not** submit the
signup, login, or password-reset forms; never typed an email, password, or card;
and never touched Stripe checkout. At each gate it stopped, filmed the wall
(screenshot + video + JSON action-log line), and asserted inspect-only facts
about the form. **Reaching the wall was the deliverable; crossing it was
forbidden.** The Stripe **$99 dossier paywall lives inside `/track` post-login**
and is structurally unreachable by anonymous traffic — the only wall a visitor
ever meets is auth.

## Findings table

| # | Class | Sev | Persona | URL | Wall kind | What was seen |
|---|-------|-----|---------|-----|-----------|---------------|
| A1 | **A** real UX/a11y nit | Low | 2 returning / 3 locked-out | `/login` | affordance | "Forgot your password?" has no resting affordance — `text-muted`, underline only on hover — vs the purple `text-primary` "Create an account" sibling. Recovery path reads as static text. |
| B1 | B expected gate | — | 1 newcomer | `/` → `/signup` | auth-gate | Primary CTA "Start your case" → `/signup` email+password form. Not submitted. |
| B2 | B expected gate | — | 2 returning | `/` → `/login` | auth-gate | "Sign in" → `/login` form ("Welcome back"). Not submitted. |
| B3 | B expected gate | — | 3 locked-out | `/forgot-password` | recovery-gate | "Reset your password" request form. Not submitted (would fire `resetPasswordForEmail`). |
| B4 | B expected gate | — | 4 deep-link | `/productize` `/track` `/market` `/cfp` | auth-gate | All four 200→redirect to `/login?redirect=<path>`. No anonymous product preview; **paywall never exposed**. |
| C1 | C harness artifact | — | 3 locked-out | `/reset-password` | none | Money-shot froze the transient "Verifying your reset link" spinner; the page's own 8 s `VERIFY_TIMEOUT_MS` falls back to an invalid-link state. Not a product defect. |

Non-finding worth stating: `/` and `/privacy` render fully for anonymous
visitors with zero errors; the privacy policy is the deepest anon-readable page
(what's stored, what isn't, third-party sharing, retention, self-hosting).

---

## Class A — real, user-facing (lead)

### A1 — `/login` "Forgot your password?" link has no resting affordance
- **Persona:** 2 (returning) & 3 (locked-out) · **URL:** https://meritai.me/login
- **Wall kind:** affordance / discoverability (not a hard wall — a soft one)
- **Actual seen:** The recovery link renders `font-medium text-muted
  underline-offset-2 hover:text-ink hover:underline` — muted grey, **no
  underline at rest**, underline appears only on hover. Its sibling "Create an
  account" renders `font-semibold text-primary` (purple). Side by side, signup
  looks clickable and recovery looks like a caption.
- **Why it matters:** the locked-out user is precisely the one under stress; a
  recovery entry point styled as static text is easy to miss, and relying on a
  hover-only underline fails pointer-less/touch and low-vision users
  (WCAG 2.1 SC 1.4.1, use of color / affordance).
- **Screenshot:** `qa-explorer/results/money-shots/persona-2-returning__1-login-wall.png`
- **Class:** A · **Severity:** Low
- **Fix line:**
  `/queue repo:meritai fix(login): give "Forgot your password?" a resting link affordance (text-primary or default underline), matching the "Create an account" link — a11y WCAG 1.4.1, help locked-out users find recovery`

## Class B — expected gates (the safety-rail stops)

### B1 — signup auth gate
- **Persona 1** · `/` → click **Start your case** → https://meritai.me/signup
- **Seen:** "Create your account", email + password fields, "Create account"
  button, "By creating an account you agree to our privacy policy". HTTP 200, no
  errors. **Stopped — form not submitted.**
- **Screenshot:** `qa-explorer/results/money-shots/persona-1-newcomer__2-signup-wall.png`
- **Class:** B · **Severity:** n/a (correct behavior)

### B2 — login auth gate
- **Persona 2** · `/` → click **Sign in** → https://meritai.me/login
- **Seen:** "Welcome back", email + password, "Sign in" button. **Stopped.**
- **Screenshot:** `qa-explorer/results/money-shots/persona-2-returning__1-login-wall.png`
- **Class:** B · **Severity:** n/a

### B3 — password-reset recovery gate
- **Persona 3** · `/login` → "Forgot your password?" → https://meritai.me/forgot-password
- **Seen:** "Reset your password", email field, "Send reset link". Submitting
  would fire `supabase.auth.resetPasswordForEmail` against a real inbox —
  **stopped, not submitted.**
- **Screenshot:** `qa-explorer/results/money-shots/persona-3-lockedout__1-forgot-password-wall.png`
- **Class:** B · **Severity:** n/a

### B4 — product surfaces redirect to login; paywall not exposed
- **Persona 4** · direct nav to `/productize`, `/track`, `/market`, `/cfp`
- **Seen:** each returns 200 then redirects to `/login?redirect=%2F<path>`
  ("Welcome back"). No anonymous preview of the O-1A tracker, paper-draft tool,
  outreach studio, or CFP finder. The Stripe $99 dossier paywall (inside
  `/track`) is therefore **never rendered to anonymous traffic** — a correct
  security posture, filmed as confirmation.
- **Screenshots:** `qa-explorer/results/money-shots/persona-4-deeplink__redirect-{productize,track,market,cfp}.png`
- **Class:** B · **Severity:** n/a
- **Note (positive):**
  `/queue repo:meritai test(e2e): keep the anon redirect-to-login contract for /productize /track /market /cfp under regression — paywall must never render to anonymous traffic`

## Class C — harness artifacts (fixed + noted)

### C1 — reset-password money-shot froze the transient verifying spinner
- **Persona 3** · https://meritai.me/reset-password (no token)
- **What happened:** the explorer screenshots at `networkidle`, which resolves
  in well under a second; the page holds a "Verifying your reset link" spinner
  until its own `VERIFY_TIMEOUT_MS = 8000` fires and falls back to an
  invalid-link state. The captured frame is the *intermediate* phase, not a
  hang — **product behavior is correct.**
- **Harness fix applied this run:** two earlier selector/timing artifacts were
  fixed before the clean pass — `didNavigate` now waits for the URL to change
  (client-side Next.js `Link` nav settles before the URL updates), and the
  reset heading assertion uses `getByRole("heading")` to avoid a strict-mode
  match against the duplicate body copy. A redundant, race-prone manual video
  attach was removed (video-on in config already saves per test).
- **Remaining note (not applied — would slow every run):** to film the terminal
  invalid-link state, the reset-password step should wait `> 8 s` before the
  money-shot. Left as a documented follow-up.
- **Screenshot:** `qa-explorer/results/money-shots/persona-3-lockedout__2-reset-password-no-token.png`
- **Class:** C · **Severity:** n/a

---

## Reproduce

```bash
cd qa-explorer
npm install
EXPLORER_BASE_URL=https://meritai.me npx playwright test
# money-shots -> results/money-shots/  ·  action-log -> results/action-log.jsonl
# videos + traces -> results/artifacts/ (gitignored)
```

## Safety-rail confirmation

No signup submit. No login submit. No password-reset submit. No email, password,
or card ever typed. No Stripe checkout reached or attempted. Every persona
stopped at its wall and filmed it. Rail held.
