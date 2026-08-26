# AGENTS.md

## Cursor Cloud specific instructions

Merit (repo internal name `agentichack` / `paperpilot`) ships **two co-existing implementations** of the same product in one repo. Know which one you are touching:

- **Phase 1 (legacy, canonical/live):** Streamlit app — `Productize.py` + `pages/Market.py` + `pages/Track.py`. Data layer is **ClickHouse Cloud**.
- **Phase 2 (rebuild):** **Next.js** frontend (`web/`) + **FastAPI** backend (`backend/`). Data layer is **Supabase** (Postgres + pgvector + Auth).
- Both share the `paperpilot/` Python core package.

### Tooling / package managers
- Python: **uv** (`pyproject.toml` + `uv.lock`). `uv` installs to `~/.local/bin` — make sure it's on `PATH`. Requires Python >= 3.11.
- Web: **npm** (`web/package.json` + `web/package-lock.json`).
- Run Python commands via `uv run ...` (see `Makefile` for the canonical targets).

### Running services (see `Makefile` for exact commands)
- **Streamlit app:** `make dev` uses `lapdog`, which is **macOS-only and not installed here** — it will fail. Use `make dev-raw` (`uv run streamlit run Productize.py`) instead. Add `--server.address 0.0.0.0 --server.headless true` when serving in the VM. Port **8501**.
- **FastAPI backend:** `make api` (`uv run uvicorn backend.main:app --reload --port 8000`). Port **8000**. `/health` never raises and reports `database: false` when Supabase is unreachable.
- **Next.js web:** `cd web && npm run dev`. Port **3000**.
- **Tests:** `make test` (`uv run pytest -q`). Tests are self-contained and need no live services/secrets.
- **Web lint:** `cd web && npm run lint` (ESLint).

### Secrets & what runs without them (important gotcha)
This product is heavily dependent on external API keys, none of which are needed just to install/lint/test:
- **`AI_GATEWAY_API_KEY`** (Vercel AI Gateway) gates **every** LLM feature (ingest, embed, draft, narratives). Any live "draft/match/ingest" path raises `RuntimeError: AI_GATEWAY_API_KEY missing` without it.
- **Streamlit runs fully offline** via `DEMO_MODE=true`: sign in with the dev fallback account (**user `Dev` / passcode `dev`** when `PAPERPILOT_USERS_JSON` is unset), then click **"Load demo cache"** on Productize to replay a cached repo→paper run from `data/demo_cache.json`. Do NOT scroll into the live-draft section at the very bottom — it triggers a live AI Gateway call and errors without the key.
- **Phase 2 web + backend need Supabase.** The Next.js app **throws on render** without `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` (home page 500s), so the dev server starts/compiles but pages won't render until those are set. Local Supabase needs the Supabase CLI + Docker (neither preinstalled). For a full Phase 2 run you need Supabase (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL`) plus the AI Gateway key.
- Optional enrichment (non-blocking): `NIMBLE_API_KEY`, `SENSO_API_KEY`, `CLICKHOUSE_*`, `DD_*`, `GITHUB_TOKEN`.

### Notes
- ClickHouse schema init only fires at Streamlit boot when `CLICKHOUSE_HOST` is set, so the app boots fine without ClickHouse creds.
- Copy `.env.example` to `.env` to configure keys locally (gitignored).
