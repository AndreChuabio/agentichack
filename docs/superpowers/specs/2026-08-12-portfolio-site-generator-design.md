# Publish: portfolio site generator

Status: approved design, not yet implemented
Date: 2026-08-12

## Context

Merit collects everything a portfolio site needs and does nothing with it. The
market profile holds name, title, about, voice and links; Productize already
ingests GitHub repos into text bundles; Track holds O-1A evidence rows. A user
who has filled all three in still has to go build their own site.

`ProfileForm.tsx` currently has a "Personal site URL (optional)" field that
collects a site the user built elsewhere. This feature makes Merit produce that
site instead of merely linking to it.

The intended outcome is a fifth surface, **Publish**, that turns profile plus
selected repos plus explicitly selected evidence into a downloadable static site
the user pushes to their own `<user>.github.io` repo. A public, shareable
artifact carrying a Merit backlink is the most effective top-of-funnel thing the
product can generate, which is why it is free rather than behind the dossier
paywall.

## Decisions locked

| Decision | Choice | Why |
|---|---|---|
| Delivery | Downloadable zip | Reuses the Productize download path. No OAuth, no stored tokens, no write access to a user's GitHub account |
| Content | Profile + repos + evidence | The repos are what make it a developer portfolio; the evidence ties it to Merit's core surface |
| Surface | New top-nav entry, `/publish` | Content spans Market, Productize and Track, so it belongs to none of them |
| Gating | Free, quota-bounded, `has_entitlement` wired dark | Same pattern the dossier paywall shipped with: gating later becomes an env var, not a code change |
| Render | Model writes prose and picks a theme from an enum; code writes all markup | Keeps the renderer pure and testable, and keeps model output out of executable markup |

## Architecture

Each new module mirrors an existing one, so no new patterns are introduced.

| New | Mirrors | Job |
|---|---|---|
| `paperpilot/site_extract.py` | `skill_extract.py` | One LLM call to a validated `SitePack` |
| `paperpilot/site_render.py` | `skill_render.py` | Pure templating to a zip. No LLM calls |
| `backend/services/site_service.py` | `plugin_service.py` | Orchestrate, reuse bundle cache, persist artifact |
| `backend/routers/site.py` | `plugin.py` | `POST /publish/site` with auth, quota and gating |
| `web/app/(app)/publish/` | `web/app/(app)/productize/` | Four-step wizard |

### Zip layout

```
<slug>/
  index.html
  style.css
  main.js
  README.md      the two git commands, and the permanence warning
```

`slug` derives from the profile name, lowercased, non-alphanumerics collapsed to
hyphens, never empty.

## Contracts

### SitePack

Returned by `site_extract`, consumed by `site_render`. Frozen dataclass.

- `hero`: name, title, tagline
- `about`: list of paragraphs
- `projects[]`: title, repo_url, blurb, tech[], highlights[]
- `evidence[]`: criterion, title, blurb, url, date
- `links`: github, linkedin, scholar, site
- `theme`: `{palette, layout}`, both enum members

`site_extract` reaches the model the same way `skill_extract` does: through
`paperpilot.gateway.get_client` with `DEFAULTS`, wrapped in `paperpilot.trace`,
so Vertex Gemini stays the default path and the gateway stays the fallback. It
introduces no second route to a model.

### Endpoint

```
POST /publish/site
  { repo_urls: string[], evidence_ids: string[], session_id?: string }
  -> { site_name, theme, html_preview, zip_base64, skipped[] }
```

- `theme` is the resolved theme after enum validation, not what the model asked
  for, so the client always reports what was actually rendered.
- `html_preview` is the rendered `index.html` as a string, with `style.css`
  inlined so it stands alone. Step 3 of the wizard shows it in a sandboxed
  iframe via `srcdoc` with scripts disabled. It is built from the same
  `SitePack` and the same template as the zip's `index.html` and differs from it
  only by that inlining, so the two are generated together rather than by two
  code paths that could drift.
- `skipped[]` names any repo that could not be fetched, with the reason.

## Data flow

```
POST /publish/site
   |
   +- CurrentUser                    caller identity
   +- RequireLLMKey                  BYOK, as Productize
   +- quotas.enforce(SITE)           5 per 30 days
   +- has_entitlement(PORTFOLIO)     price env unset means free
   |
   +- per repo: cached repo_bundle artifact, else github_ingest.fetch_repo
   +- evidence: WHERE id = ANY(evidence_ids) AND user_id = caller
   +- user_profile row
   |
   v
site_extract.build_pack(...) -> SitePack        one LLM call
   v
site_render.build_site_zip(pack)                pure, no LLM
   v
persist session_artifacts kind="portfolio_site" best-effort
   v
response
```

Bundle reuse follows `plugin_service._load_bundle`: when `session_id` names a
session that already stored a `repo_bundle` artifact, that text is used rather
than re-fetching from GitHub.

## Privacy

Evidence rows are visa case material. The governing rule is that **the request
is the only authority, on every build**.

1. The build includes exactly the `evidence_ids` in that request body. The
   server never widens the set.
2. Every requested id is checked against `user_id = caller` before it is read.
   Without that check, guessing a uuid publishes another user's case material.
3. `metadata.publish` is written so the UI can pre-tick boxes on a later visit.
   **The build never reads it.** This closes the path where a stale flag
   republishes an item the user later thought better of.
4. Step 2 of the wizard lists verbatim every item that will become public.
5. The zip's `README.md` states that pushing makes the content world-readable
   and permanent in git history.

## Escaping

Every interpolated value — profile text, model prose, repo README fragments,
evidence titles — passes through `html.escape(..., quote=True)` at the
templating boundary. There is no raw passthrough anywhere and the model never
emits markup, only prose and two enum values.

`href` values are validated as `http` or `https` before rendering. This is what
stops a `javascript:` payload pasted into the GitHub URL field from reaching the
published page.

Theme values are validated against their enums. An unrecognised value falls back
to the default rather than raising, so a model that invents a palette name costs
a default theme rather than the build.

## Entitlements change

`entitlements.billing_enabled()` reads `STRIPE_PRICE_DOSSIER` and nothing else,
so it means "is the dossier paywalled" rather than "is this product paywalled".
A second product cannot ship dark independently through it.

It becomes `billing_enabled(product)` reading `STRIPE_PRICE_{PRODUCT}`, with
`DOSSIER` behaviour unchanged. `has_entitlement` passes its `product` argument
through. A new `PORTFOLIO = "portfolio"` key is added beside `DOSSIER`.

## Quota

`backend/quotas.py` gains:

```python
SITE = Quota(kind_prefix="site_build", limit=5, window_days=30, noun="site build")
```

alongside the existing `DOSSIER`, `NARRATIVE` and `ASSIST`.

## Error handling

Follows `plugin.py` exactly: 400 on empty or invalid input, 403 on session
ownership, 429 from the quota, 502 on pipeline failure, and deliberate
`HTTPException`s re-raised rather than masked as a generic 502.

Two additions:

- A repo that fails to fetch drops that project card and names the reason in
  `skipped[]` rather than failing the whole build.
- Persistence to `session_artifacts` is best-effort and never blocks the
  download, matching the stated posture in `export.py`.

## Testing

The render step is pure, so it tests with no LLM anywhere near it.

- Golden-file test of `build_site_zip` against a fixture `SitePack`.
- Hostile input: `<script>`, `javascript:` URLs, and quote-breaking attribute
  payloads in profile fields appear inert in the output.
- Authorization: an evidence id owned by another user is rejected.
- Opt-in: an evidence row absent from the request never reaches the zip, even
  when its `metadata.publish` is true.
- Quota: the sixth build within thirty days returns 429.
- Theme fallback: an unrecognised palette renders the default.
- Repo failure: an unreachable repo yields a `skipped[]` entry and a zip that
  still builds.
- Preview parity: `html_preview` and the zip's `index.html` carry the same
  `<body>` for one fixture pack, so the thing reviewed is the thing downloaded.
- Playwright e2e over the four wizard steps, using the existing `web/e2e`
  harness and `playwright.config.ts`.

## Out of scope for v1

GitHub OAuth push, custom domains and `CNAME`, Merit-side hosting, analytics,
and multi-page sites. The zip plus two git commands is the whole delivery.

## Verification

1. `make test` (or `pytest`) green, including the new render and authorization
   tests.
2. Backend up, then `POST /publish/site` with one real repo and one evidence id;
   confirm the response zip contains `index.html` and that the evidence appears.
3. Repeat with an evidence id belonging to a different user; confirm rejection.
4. Unzip, open `index.html` in a browser, confirm it renders standalone with no
   network calls.
5. Push the unzipped contents to a scratch `<user>.github.io` repo and confirm
   GitHub Pages serves it.
6. Run the build six times in a month and confirm the sixth returns 429.
