# The Merit QA loop

A recurring sweep of a **deployed** Merit that answers one question the test
suite cannot: is the thing that is actually running correct?

`npm test` and the Playwright suite prove the *code* is right against a local
dev server. They stay green while the deployed frontend calls a backend that was
never redeployed, while a migration has not been applied, and while the whole
suite is unknowingly pointed at a different application. Each of those has
happened here. This loop catches that class.

---

## The runner

```
web/qa/run-live.mjs
```

```bash
cd web
npm run qa:live -- \
  --target https://merit-<hash>-andre-chuabios-projects.vercel.app \
  --api    https://paperpilot-api-production.up.railway.app \
  --out    /tmp/meritqa
```

| Flag | Meaning |
|---|---|
| `--target` | The deployed frontend. Required. A deep link is trimmed to its origin. |
| `--api` | The backend the frontend talks to. Optional but **strongly wanted** -- without it nothing checks for deploy skew, which is invisible from the UI. |
| `--out` | Directory for `findings.json`, `qa.webm`, and break screenshots. Created if absent. Required. |
| `--notes` | Standing corrections, recorded as `carried_corrections`. |

### Exit codes

Deliberately identical to claudemeow's runner:

| Code | Meaning |
|---|---|
| `0` | The run produced findings -- **even if breaks were found**. Breaks are data, not runner failures. |
| `2` | Bad invocation (missing or invalid `--target` / `--out`). |
| `1` | A real runner failure (browser would not launch, output not writable). |

If you wire this into anything, do not treat a non-zero exit as "QA found
problems". Non-zero means the runner never got to look.

---

## What it checks

| Flow | Why it is in here |
|---|---|
| **identity** | The served page is Merit. Every later result is meaningless if it is not -- a full suite once came back green against an unrelated app squatting on port 3000. Failing this aborts the rest of the walk on purpose. |
| landing / login / signup / privacy | Public pages render their real copy. Waits for the text rather than regexing the first response, because these hydrate client-side. |
| gated routes | `/market`, `/productize`, `/track`, `/publish`, `/cfp` bounce an anonymous visitor to `/login`. |
| unknown portfolio slug | `/u/<nonsense>` returns 404. This is the published-site draft boundary: RLS exposes only `published = true`, so a draft returns no row. A 200 here would mean drafts are publicly reachable. |
| api health | `/health` answers and reports `database: true`. |
| api routes | Each route the frontend calls answers **401**, not 404. |

That last row is the one that earns the loop. **401 means the route exists and
refused an anonymous caller. 404 means the deployed API does not have this
build** -- and in the browser that is indistinguishable from a broken feature.
A frontend deployed ahead of its backend fails exactly this check and nothing
else.

`/health` also reports a `build` marker. When it is absent the run raises a
suggestion, because without it there is no way to tell which build is serving
and a rollout can only be confirmed by guessing.

---

## Output

`<out>/findings.json`, shaped to claudemeow's contract so the bridge can read it
with no adapter:

```jsonc
{
  "target": "https://…",
  "api": "https://…",
  "flows":   [{ "step": "landing", "url": "https://…", "ok": true }],
  "breaks":  [{ "where": "…",
                "kind": "console-error|http-4xx|http-5xx|stuck|error-banner",
                "detail": "…",
                "shot": "<out>/break-01.png" }],
  "suggestions": ["…"],
  "video": "<out>/qa.webm",
  "logged_in": false,
  "carried_corrections": false
}
```

Plus an always-on 1280x800 `qa.webm` of the walk and one screenshot per break.

---

## Running it as a loop on this laptop

Claude Code's `/loop` runs a prompt on an interval in the current session:

```
/loop 30m run the Merit live QA sweep with web/qa/run-live.mjs against the
current preview and the production API, then report only new breaks
```

Or self-paced, letting the model choose the cadence:

```
/loop run the Merit live QA sweep and tell me only when something breaks
```

Two things to know before leaving one running:

- **The session must stay open.** This loop lives in a Claude Code session on
  the laptop; closing it ends the loop. That is the whole reason to port it to
  the mini, which stays up.
- **A CLI preview URL is not stable.** `vercel deploy` mints a new hostname each
  time, so a loop pinned to `merit-<hash>-…vercel.app` starts failing against a
  dead host the moment you redeploy. Point it at a stable alias or at
  `https://meritai.me` for anything long-lived.

---

## Porting it to the mini and MeowConcierge

The runner was written against claudemeow's contract so this is a change of
invoker, not a rewrite.

### What already exists on that side

`claudemeow/qa/run.mjs` takes `--target <alias|url> --out <dir>` and writes the
same `findings.json` / `qa.webm` / `break-*.png`. Merit is already a registered
alias:

| Alias | URL | Auth | Mode |
|---|---|---|---|
| `meritai` | `https://meritai.me` | `~/.claudemeow-qa-auth/meritai.json` | browse |
| `meritai-fn` | `https://meritai.me` | `~/.claudemeow-qa-auth/meritai-qa.json` | functional |

`meritai-fn` points at a **dedicated throwaway QA account**; the real session is
never used for functional runs.

### The Telegram grammar

```
/loop 6h qa meritai-fn
/loop qa meritai            # one sweep now, no schedule
/loop list                  # what is scheduled
/loop stop <n>
```

### Interval floors that will refuse you

From `claudemeow/src/claudemeow_bridge/domain/loops.py`:

- **1h** minimum for any loop (`MIN_INTERVAL_SECONDS = 3_600`)
- **6h** minimum for a *functional* qa target
  (`FUNCTIONAL_MIN_INTERVAL_SECONDS = 21_600`) -- a functional sweep fills and
  submits real forms on Merit's key, and Merit meters those actions (dossier 3
  per month, narrative 30 per month). Four fires a day stays well under.
- **10** active loops across all chats (`MAX_ACTIVE_LOOPS`)

The floors are enforced with the number named rather than silently clamped, so a
refused `/loop 30m qa …` tells you the minimum.

### Two ways to carry this runner over

**A. Register the deployment sweep as a new alias.** Cheapest. The bridge's
alias table accepts out-of-band records via `CLAUDEMEOW_QA_TARGETS`, one per
line in `alias=url|auth|mode|fixtures`. A browse-mode alias pointed at the
preview gets you the journey walk on a schedule immediately, but **not** the API
route checks -- claudemeow's runner has no `--api` concept.

**B. Port `run-live.mjs` into `claudemeow/qa/`.** Preserves the API deploy-skew
check, which is the highest-value thing here and the part claudemeow does not do.
It needs `--api` threaded through `qa/lib/args.mjs` as an alias field, mirroring
how `fixtures` is already carried. The findings shape needs no change.

Prefer **B** if you want the loop to catch a frontend shipped ahead of its
backend. Prefer **A** if you just want a recurring persona walk today.

### What does not change

- `findings.json` shape, so the bridge's summariser works untouched
- Exit-code semantics, so a run with breaks is not mistaken for a crashed runner
- `qa.webm` and break screenshots, which sync to Drive at
  `CLAUDEMEOW_QA_DRIVE_DIR` (defaults to the shared `claudeMeow` folder)

### What does change

- **Where it runs.** The mini, under launchd, not this laptop.
- **Who fires it.** The bridge on a schedule, not a person in a terminal.
- **Auth.** The local runner is anonymous-only. Any authenticated journey needs
  a Playwright `storageState` at `~/.claudemeow-qa-auth/`, and for functional
  mode a throwaway account -- never the real one, because a functional sweep
  submits real forms.

---

## Local Playwright suite

Separate thing, same directory. Runs against local `next dev`:

```bash
cd web
PLAYWRIGHT_PORT=3131 npx playwright test
```

**Always set `PLAYWRIGHT_PORT` to something free.** `reuseExistingServer` adopts
whatever is already listening, and a second Next project on 3000 means the whole
suite silently runs against that app. `e2e/harness.spec.ts` fails loudly when
that happens, naming what it found -- but only after you have wasted a run.

---

## Adding a check

Put it in `PUBLIC_PAGES`, `GATED_PAGES`, or `API_ROUTES` at the top of
`run-live.mjs` if it fits one of those shapes. Otherwise add a block that pushes
one entry to `flows` and calls `addBreak` on failure.

One rule: **verify the check can fail.** Point the runner at something wrong and
confirm it reports a break. A check that cannot fail is worse than no check,
because it reads as evidence. That is not hypothetical here -- a QA run once
reported a green `/u/<slug>` 404 against an entirely different product, and an
earlier Playwright spec asserted only that an unknown slug 404s, which passes
whether RLS is on, off, or bypassed.
