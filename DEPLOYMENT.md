# Deployment

How previews and production get built for this repo, and what to check when
they don't.

## The setup

- **Frontend** (`web/`, Next.js): deployed on Vercel, project `<your-project>`
  under the `<your-team>` team. Connected to this GitHub repo
  (`AndreChuabio/MeritAI`) via Vercel's native GitHub integration.
- **Backend** (`backend/`, FastAPI): deployed separately on Railway
  (`paperpilot-api-production.up.railway.app`), not covered by this doc.
- **CI**: `.github/workflows/ci.yml` runs on every PR into `main` or
  `develop` (and on direct pushes to either) — backend `pytest`, frontend
  lint/typecheck/build, then a Playwright E2E smoke suite
  (`web/e2e/smoke.spec.ts`) against every route.
- **Branch protection**: for CI to actually block a bad merge (not just
  report red after the fact), `develop` (and ideally `main`) need a GitHub
  branch protection rule requiring the three `ci.yml` job names — **Backend
  tests**, **Frontend lint, typecheck, build**, **Frontend E2E smoke
  tests** — to pass before merging. Set this up under repo Settings →
  Branches → Add branch protection rule. Without it, checks run and report
  status but a PR can still be merged while they're red.

## Branch previews (the part that broke, and the fix)

Vercel's GitHub integration is supposed to auto-build a preview deployment
for **every push to every branch**, no extra config needed — that's the
default. If pushes to your branch aren't showing up in
`vercel.com/<your-team>/<your-project>` → Deployments, the GitHub
connection has silently dropped. Fix:

1. Vercel dashboard → `<your-project>` project → **Settings → Git**.
2. Under "Connected Git Repository," disconnect and reconnect
   `AndreChuabio/MeritAI`. This re-establishes the webhook.
3. Push a new commit (a re-push of an existing commit does **not** retrigger
   anything — only new pushes fire the webhook). You should see a build
   start within seconds.

You can tell a deployment was genuinely webhook-triggered vs. manually
uploaded by checking its metadata: a real one carries `source: "git"` and
`githubCommitSha` / `githubDeployment` fields. One triggered by `vercel
deploy` from a CLI or an ad-hoc file upload will not have those.

**`develop`** is set up as the standing branch for previewing in-progress
work — it always has a stable alias:

```
https://<your-project>-git-develop-<your-team>.vercel.app
```

Push to `develop` (or merge into it) and that same URL updates automatically
within about a minute. Feature branches also get their own one-off preview
URLs the same way; check the Vercel dashboard or the PR's Vercel status
check for the link.

## Root Directory (the other part that broke)

Vercel's project setting **Settings → General → Root Directory** must be
`web` — that's where the actual Next.js app lives; the repo root also has an
unrelated legacy `pages/` folder (Python files for the old Streamlit app)
that looks superficially like a Next.js Pages Router directory. If Root
Directory ever gets reset to blank/`./`, Vercel builds from the repo root
instead, Next.js finds no real routes, and every page 404s. The build log
gives it away immediately: a broken build's "Route" summary shows only
`Route (pages) ─ ○ /404`; a working one shows `Route (app)` with every real
page (`/`, `/cfp`, `/login`, etc.) listed. If every route 404s in production
but CI's `npm run build` job is green, check this setting first — CI always
builds from `web/` explicitly and will never catch a Root Directory drift.

This has already happened once (root-caused to an ad-hoc deployment made
without specifying `rootDirectory`, which appears to reset the project's
persisted setting as a side effect). If you're deploying manually outside
the normal git-push flow, always pin the root directory explicitly.

## Backend: Vertex AI (Gemini) in production

Merit-dime surfaces (repo ingest, the help assistant) run first-party
Gemini on Vertex AI -- a Google Cloud product -- instead of proxying
through the Vercel AI Gateway, but only when `VERTEX_PROJECT` is set. It
being *supported* in code is not the same as it being *on*: the Railway
backend service (`SERVICE_KIND=api`) needs these variables set in its
Railway environment for the deployed app to actually route through Vertex:

- `VERTEX_PROJECT` -- the GCP project id.
- `VERTEX_LOCATION` -- defaults to `us-central1` if unset.
- `GOOGLE_APPLICATION_CREDENTIALS_JSON` -- the service-account JSON
  contents, pasted in as a Railway secret. `scripts/railway_start.sh`
  writes it to `/tmp/gcp-sa.json` and points
  `GOOGLE_APPLICATION_CREDENTIALS` at it before the app starts; without
  this variable the app boots fine but silently falls back to the Gateway
  path (BYOK surfaces are unaffected either way -- see `.env.example`).

Per-call token usage is written to the `gemini_usage` Supabase table
(`supabase/migrations/*_gemini_usage.sql`) and to structured log lines --
check either to confirm Vertex is actually being hit in a given
environment, rather than just configured.

## Supabase Auth redirect URLs

Any Supabase Auth flow that redirects back into the app (password reset via
`resetPasswordForEmail`, magic links, OAuth) only honors a `redirectTo` URL
that's on the project's allowlist. An unlisted URL is silently swapped for
the configured Site URL instead — which will send a tester's password-reset
email to `localhost:3000` instead of whatever preview they're actually
testing. Add these to Supabase dashboard → **Authentication → URL
Configuration → Redirect URLs**:

```
https://<your-project>-git-develop-<your-team>.vercel.app/**
https://<your-project>-git-*-<your-team>.vercel.app/**   # every branch preview
https://<your-production-domain>/**
```

## What to do for a new feature branch

1. Branch off `develop`, do the work, push.
2. Vercel auto-builds a preview at a branch-specific URL — no action needed.
3. Open a PR into `develop`. CI runs automatically (see above) and the PR
   gets a Vercel preview-deployment status check; Vercel also comments the
   exact preview URL on the PR.
4. If you want a shared, always-current URL for the team to poke at
   mid-development (not tied to a specific PR), merge/rebase into `develop`
   and use the stable alias above.
5. `develop` periodically merges into `main` (production) once it's in a
   good state — via a dedicated promotion PR, not ad-hoc pushes. `main`
   should only ever receive changes that have already been verified on
   `develop`.

## Local reproduction

If a CI failure or preview build doesn't make sense from the logs alone:

- Backend: `uv sync --all-groups && uv run pytest -q`
- Frontend: `cd web && npm ci && npm run lint && npx tsc --noEmit && npm run build`
- E2E: `cd web && npx playwright install --with-deps chromium && npm run test:e2e`
  (the suite runs against placeholder Supabase env vars baked into
  `playwright.config.ts` — no real Supabase project needed for the smoke
  suite itself, since it only checks that public pages render and gated
  pages redirect to `/login`.)

## Known gaps

- No environment currently runs the full app against a live Supabase
  project in CI. The E2E suite is a smoke test (routes render, auth
  redirects work) — it does not exercise real data flows like `/cfp`'s
  fetch-and-filter behavior end to end.
- The backend has no CI/CD pipeline documented here yet; it deploys to
  Railway, but the trigger mechanism (auto vs. manual) isn't captured in
  this doc. Worth writing up if it bites someone.
