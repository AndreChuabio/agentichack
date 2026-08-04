# Contributing to Merit

Merit is a small, opinionated codebase. This document covers how to get a
local setup running and what a change needs before it is mergeable.

## Getting set up

```bash
git clone https://github.com/AndreChuabio/MeritAI.git
cd MeritAI
cp .env.example .env
# Put your AI_GATEWAY_API_KEY in .env -- see the README for what it is and
# where to get one. Add Supabase vars if you are working on the backend or
# web app; add ClickHouse vars only if you are working on the legacy
# Streamlit surface.
uv sync
make test
```

For the Next.js frontend:

```bash
cd web
cp .env.example .env.local
npm install
npm run dev
```

## Two surfaces, one pipeline

- `backend/` (FastAPI) + `web/` (Next.js) is the primary, actively developed
  surface. Auth and persistence run through Supabase; the LLM pipeline is
  bring-your-own-key (the caller's Vercel AI Gateway key travels in the
  `X-LLM-Key` header and is never logged or stored -- see
  `paperpilot/redaction.py` and `backend/byok.py`).
- `Productize.py` + `pages/` (Streamlit) is the original hackathon surface.
  It still works and shares the same `paperpilot/` pipeline code, but it is
  not where new feature work should land unless the change is
  Streamlit-specific.

Both surfaces import from `paperpilot/`. Put pipeline logic there, not in a
route handler or a Streamlit page, so it stays shared.

## Autonomous tickets

This repo uses an executor bot: any issue labelled `queued` is picked up automatically on the team's always-on machine, worked on a feature branch, and returned as a draft PR labelled `needs-review`. No manual PR creation needed — label the issue and it flows through the pipeline.

## Before opening a PR

1. `make test` must pass. Add or update tests for any behavior change --
   this codebase treats untested auth, isolation, and quota logic as a bug
   waiting to happen.
2. Run the frontend typecheck if you touched `web/`: `cd web && npx tsc --noEmit`.
3. Do not commit secrets. `.env`, `.env.local`, and any `*.key` / `*.pem`
   file are gitignored; keep it that way. If you add a new required config
   value, add it (empty) to `.env.example` or `web/.env.example` with a
   comment on where to get it and whether it is required or optional.
4. Do not log or persist a caller's API key. If you touch `backend/byok.py`,
   `paperpilot/gateway.py`, or `paperpilot/redaction.py`, re-run
   `tests/test_key_never_logged.py` and think about whether your change
   opens a new path for a key to reach a log line, a database row, or a
   response body.
5. Keep multi-tenant isolation intact. Every Supabase read/write that is
   scoped to a user must filter by that user's id. `tests/test_supabase_client_tenancy.py`
   and `scripts/verify_cascade_delete.py` are the reference tests for this.

## Code style

- Python: PEP 8, type hints on new functions, docstrings on public
  functions. No emojis, no exclamation marks, in code or comments.
- TypeScript: avoid `any`; define explicit interfaces for API payloads.
- Do not rename the `paperpilot` package -- it is imported across the whole
  repo and a rename buys nothing.
- No billing code. Merit is bring-your-own-key; it does not meter, invoice,
  or charge anyone.

## Reporting a security or privacy issue

Merit handles immigration-petition evidence and outreach content for real
people. If you find a way for one user's data to reach another user, or a
way for an API key to leak into a log or a response, do not open a public
issue -- email andre102599@gmail.com with details first.

## License

By contributing, you agree your contribution is licensed under the MIT
License in `LICENSE`.
