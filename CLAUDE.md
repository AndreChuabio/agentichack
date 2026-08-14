# Merit — Claude conventions

This repo is watched by the claudeMeow always-on executor. Read this file
before doing anything; it reflects how Merit actually runs, not a template.

## What this is

Merit turns a GitHub repo into a research-paper draft, drafts outreach copy,
and tracks an O-1A visa petition against the 8 USCIS criteria. Two surfaces,
one pipeline:

- **Primary:** FastAPI (`backend/`) + Next.js (`web/`) — Supabase auth +
  Postgres/pgvector, BYOK LLM calls via Vercel AI Gateway (caller's key rides
  the `X-LLM-Key` header, never logged or stored), Stripe paywall on the O-1A
  dossier. Backend deploys to Railway, frontend to Vercel.
- **Legacy:** Streamlit (`Productize.py` + `pages/`) — the hackathon surface;
  additionally needs ClickHouse. Still works; new feature work does not land
  here unless it is Streamlit-specific.
- Shared pipeline logic lives in `paperpilot/` and only there — never in a
  route handler or a Streamlit page.

## This repo is part of the claudeMeow fleet

This repository is one of several worked by **claudeMeow**, a shared automation
system owned by the `Meowteam6` org (the org name is why there are six repos).
The system is defined in [`Meowteam6/claudemeow`](https://github.com/Meowteam6/claudemeow);
this section is the short version an agent working *here* needs.

### How work arrives

**GitHub Issues are the queue.** An issue labelled `queued` is a work order. An
always-on executor on Andre's M4 Mac mini polls every 60s, claims the issue by
swapping `queued` for `in-progress` (the label *is* the mutex — that is how two
machines share one queue safely), creates a git worktree, and runs a headless
Claude session against the ticket.

The run ends in exactly one of two ways:

- **A draft PR**, which waits for a human.
- **`blocked`**, with the agent's own explanation in a comment.

The executor is denied `gh pr merge`, `gh pr ready`, and `gh pr close` at the
tool level. It physically cannot merge its own work or take a PR out of draft.
**A human merges. Always.**

### What this means for you

- **Write tickets, not prose.** A `queued` issue is executed literally. Give it a
  Problem, a What to build, and acceptance criteria. Vagueness becomes a wasted
  run.
- **Keep tickets small.** The inner session runs under `MAX_TURNS=150`. A run
  that hits the cap **commits nothing and leaves no summary** — the work is lost
  and the money is spent. If a ticket looks like it may run long, split it and
  say so in the body.
- **At most three sessions run at once** across the whole machine (memory-bound,
  16 GB). Filing ten tickets does not make them go faster.
- **Never assume a PR was reviewed** because it exists. Draft is the default
  state, not a signal.

### Conventions this fleet enforces

- **Branches:** `type/IS-NNN-description` (IS = the GitHub Issue number)
- **Commits:** Conventional Commits — `type(scope): description`
- **No ticket refs in code or comments** — CHANGELOG only
- **Never `--no-verify`.** Fix the hook, not the flag.

### Talking to the fleet

**MeowConcierge** (`@meowteam_bot` on Telegram) is the human front-end. It files
tickets (`/queue`), reports per-repo state (`/status`), scopes work out loud
(`/design`), researches into docs (`/study`), and runs scheduled rounds
(`/loop`). It is **read-only** when answering questions — it can create work but
never performs it. Everything it files lands in the same GitHub queue described
above, so nothing here depends on Telegram being up.

The fleet spans more than one machine (Andre's Mac mini and Nikki's laptop), so
an issue may be claimed by either. Stale claims are swept and requeued
automatically after 30 minutes.

## Commands (all verified against the Makefile / package.json)

```bash
uv sync                     # install Python deps (uv-managed, Python >= 3.11)
make test                   # uv run pytest -q — full suite, no API keys needed
make api                    # FastAPI backend with reload on :8000
make dev-raw                # legacy Streamlit UI, no telemetry wrapper
cd web && npm install && npm run dev    # Next.js frontend on :3000

# Frontend checks (what CI runs):
cd web && npm run lint && npx tsc --noEmit && npm run build
cd web && npx playwright install --with-deps chromium && npm run test:e2e

# Legacy-surface only (needs ClickHouse configured):
uv run python scripts/run_migrations.py
```

`make dev` / `make dev-local` wrap Streamlit in Lapdog (brew-installed,
macOS-only) — use `make dev-raw` unless you are debugging telemetry.
`make ping` is an LLM smoke test and needs a real `AI_GATEWAY_API_KEY`.

There is no ruff/mypy/pre-commit config in this repo. The gate is
`make test` plus CI (`.github/workflows/ci.yml`: backend pytest, frontend
lint + typecheck + build, Playwright smoke suite). Style follows
CONTRIBUTING.md: PEP 8, type hints on new functions, docstrings on public
functions, no emojis or exclamation marks; TypeScript avoids `any`.

## Ticket workflow

- Issues labelled `queued` are picked up by the executor on the Mac mini.
  It works the ticket on a branch and opens a **draft PR**. The executor
  keeps the issue label in `in-progress`; a human changes it to `needs-review`
  after reviewing the PR. `blocked` marks work that cannot proceed (see
  "This repo is part of the claudeMeow fleet" above for more detail).
- Branch format: `type/IS-NNN-description` (NNN = GitHub Issue number).
- Commits: Conventional Commits, `type(scope): description`. Enforced by
  `.claude/hooks/guards/commit-guard.sh`; install it per clone with
  `cp .claude/hooks/guards/commit-guard.sh .git/hooks/commit-msg`.
- Never `--no-verify`. Fix the hook, the branch name, or the message.
- No ticket refs in commit messages or code — link the issue with
  `Closes #N` in the PR body.
- Base PRs on `main`. DEPLOYMENT.md describes a `develop`-first flow, but
  `develop` is currently behind `main` and recent work merges to `main`
  directly; CI runs on PRs into either.

## Merit-specific guardrails

- **Never log or persist a caller's API key.** If you touch
  `backend/byok.py`, `paperpilot/gateway.py`, or `paperpilot/redaction.py`,
  re-run `tests/test_key_never_logged.py` and look for new leak paths.
- **Multi-tenant isolation is load-bearing.** Every user-scoped Supabase
  read/write filters by that user's id; `tests/test_supabase_client_tenancy.py`
  is the reference. This app holds immigration-petition evidence — one
  user's data reaching another is the worst bug this repo can have.
- Do not rename the `paperpilot` package.
- Secrets live in `.env` (gitignored). A new config value goes into
  `.env.example` (empty, with a comment) — never a real value in the repo.
- Behavior changes ship with tests; untested auth, isolation, or quota
  logic is treated as a bug.
- CONTRIBUTING.md predates the Stripe dossier paywall; where it conflicts
  with the code on `main` (e.g. "no billing code"), the code wins.

## claudeMeow rules that do NOT apply here

Stated plainly so nobody imports them by habit:

- No `changelog.d/` fragments or CHANGELOG assembly — this repo has no
  changelog workflow.
- No hexagonal `src/<domain>/{domain,application,adapters}` layout — keep
  the existing `backend/` + `paperpilot/` + `web/` structure.
- No pytest markers (`unit`/`integration`/`e2e`) — the suite is not
  classified and adding markers piecemeal helps nobody.
- No `pre-commit run --all-files` — there is no `.pre-commit-config.yaml`.
- No vendored `.claude/{commands,skills,agents}` and no bash test suites —
  those are claudeMeow-repo internals.

What does carry over: Conventional Commits, the `type/IS-NNN-description`
branch format, the secrets guard (wired in `.claude/settings.json`), TDD
for behavior changes, and draft-PR-plus-review before anything merges.
