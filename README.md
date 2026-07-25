# Merit

Merit turns a GitHub repo into a research paper draft, drafts personal-brand outreach copy for the person behind it, and tracks an O-1A extraordinary-ability visa petition against the 8 USCIS criteria -- three agentic surfaces on one stack, every LLM call traced.

## The one key you need

Merit calls three model providers: Google for repo ingest, Anthropic for drafting, and OpenAI for embeddings. No single provider key can run the pipeline. One **Vercel AI Gateway** key routes to all three.

Get one free at https://vercel.com/dashboard/ai-gateway.

Senso (brand-kit tone retrieval) and Nimble (contact discovery) are optional enhancements layered on top. Nothing breaks without them -- Merit falls back to a direct LLM call and hides the affected UI elements when their keys are unset.

## Run it

```bash
git clone https://github.com/AndreChuabio/MeritAI.git
cd MeritAI
cp .env.example .env
# Put your AI_GATEWAY_API_KEY in .env. That is the only required key.
uv sync
make test

# FastAPI backend + Next.js web app (the primary, modern surface):
make api                              # backend on :8000
cd web && npm install && npm run dev  # frontend on :3000, needs web/.env.example filled in
```

The backend also needs Supabase configured (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, etc. in `.env`) for auth and persistence -- see `.env.example`. The original hackathon-era Streamlit app (`make dev`) still runs and is documented under "Quickstart" below; it is a separate, legacy surface that additionally needs ClickHouse.

## What this is not

Merit is a document-preparation tool. It drafts research papers, outreach messages, and O-1A petition narratives for a human to review, edit, and use -- it is not a law firm, it does not practice law, and nothing it generates is legal advice. See the in-app disclaimers and the privacy policy (`web/app/privacy`) for what is stored and who submitted content is shared with.

---

Built at the **Agentic Engineering Hack NYC**, 2026-05-23, at Datadog HQ. Hardened after the hackathon for multi-tenant use: passcode/Supabase auth, per-user data isolation, bring-your-own-key billing (Merit never stores or logs a caller's API key), an O-1A Evidence Ledger that replaces the heuristic gauge with declared evidence against the 8 USCIS criteria, per-criterion narrative drafting, and a reportlab-rendered PDF dossier for attorney handoff.

---

## What it does

The section below describes the original three-page Streamlit app (`Productize.py` entry + `pages/Market.py` + `pages/Track.py`), which the post-hackathon `backend/` (FastAPI) + `web/` (Next.js) rebuild carries forward on the same agentic spine with BYOK auth and Supabase persistence. The underlying pipeline logic (`paperpilot/`) is shared by both surfaces.

### Productize -- repo to paper draft for a matched venue

1. **Ingest.** Pulls README + file tree + ranked source files from any GitHub repo. Concatenates into a single bundle under a 600K-token cap.
2. **Summarize.** Sends the bundle to Gemini 2.5 Flash through Vercel AI Gateway (1M-context window). Returns a structured `ResearchSummary`: problem, contribution, method, results, limitations, keywords.
3. **Match.** Embeds the summary and ranks 53 CFPs (41 curated + 12 Nimble-discovered) in ClickHouse Cloud by semantic fit + deadline proximity. **Augmented with live Nimble Search:** queries the open web in parallel and merges the top 3 hits into the candidate pool. Venue cards carry a `LIVE · Nimble` or `Curated` badge.
4. **Draft.** Streams the paper section-by-section through Claude Sonnet 4.6. Pre-pended with **Senso KB tone exemplars** retrieved per `(venue, section)`. Related-work citations are gated against an arxiv corpus pre-filter; unsanctioned `[arxiv:...]` markers are stripped post-hoc with a visible warning.
5. **Export.** LaTeX + BibTeX, ready to open in Overleaf. Auto-persisted to ClickHouse `session_artifacts`.
6. **Extract Claude plugin.** A second pass over the same repo bundle identifies reusable units and packages them as a complete Claude Code plugin: `SKILL.md` files, slash commands, subagents, lifecycle hooks, MCP build prompts, all bundled with a `plugin.json` in the standard `~/.claude/plugins/<name>/` layout. Drop-in zip.

### Market -- outreach drafting on a Senso brand kit

- **Personal Brand tab.** Save / load a profile (name, title, voice, links, resume) into a Senso `brand_kit` so all subsequent drafts inherit the user's voice.
- **Generate Content tab.** Pick a purpose (VISA, SPEAKING, COLLAB, NETWORK), describe the goal, get drafts back via Senso's content-generation pipeline. Each draft includes a `cost_source`-tagged trace.
- **Search People tab.** Discover GitHub users / open-source maintainers via the `github_repos.py` helper.
- **Blast tab.** Schedule + dispatch drafts to outbound channels.

### Track -- O-1A evidence ledger + petition-quality narrative drafting

Track was rebuilt post-hackathon around real petition workflow. The headline is a count, not a gauge, and the source of truth is what the user has actually declared.

**Headline metric.** "X of 8 O-1A criteria satisfied" with 8 status pills above the tabs. USCIS requires evidence in at least 3 of 8 criteria to qualify; the pills go green as the user declares items.

**Evidence Ledger tab.** One expander per USCIS O-1A criterion (awards, membership, published material about you, judging, original contributions, scholarly articles, critical role, high salary). Each expander lets the user declare items (title, description, evidence URL, date), list and delete existing items, and stream a per-criterion **petition-quality narrative** via `paperpilot/outreach/evidence_draft.py` -- a ~200-word paragraph an immigration attorney can lift verbatim. Stored in ClickHouse `o1_evidence` (ReplacingMergeTree, soft-delete via tombstone).

**Download O-1A dossier (PDF).** Two-step button on the Dashboard tab. Drafts all 8 narratives sequentially via the AI Gateway, bundles them with declared evidence per criterion and a cover page, and emits a reportlab-rendered PDF ready for attorney handoff. End-to-end ~15-40s.

**Dashboard tab.** Auto-derived heuristics from Scholar, Senso, and `outreach_log` -- demoted under a caption that says "not USCIS-official". The cumulative-citations chart now uses live `by_year` data parsed from Scholar HTML, not the mock seed.

**Scholar transparency.** When the Nimble Scholar fetch fails or no Scholar URL is configured, the page renders a yellow banner with an explicit reason -- replaces the silent mock-fallback that previously showed another user's seeded sample data.

### Observability throughout

Every LLM call wrapped by `trace.step(...)` → in-process buffer (UI right rail) + ClickHouse `trace_log` (audit) + **Lapdog** local dashboard + **Datadog LLM Observability** cloud forward. Cost+token pill in the right rail sums every `.end` event with a `(est.)` tag when the Gateway omits usage on streamed responses.

---

## Architecture

```
              Streamlit UI (localhost)
                       |
        wrapped by:  lapdog
                       |
        +--------------+---------------+
        |              |               |
   GitHub API   Vercel AI Gateway   ClickHouse Cloud
   (PyGithub)   - Gemini ingest    - cfp(scope_emb)
                - Claude draft     - arxiv(emb)
                - text-embed-3     - trace_log
                       |
                 arxiv API (Python)
                 (citation grounding)
```

| Layer | Stack | Sponsor |
|-------|-------|---------|
| LLM routing | OpenAI-compatible client → multi-provider | **Vercel AI Gateway** |
| Long-context ingest | Gemini 2.5 Flash, 1M-ctx | **DeepMind** |
| Drafting | Claude Sonnet 4.6, streamed | **Anthropic** |
| Vector search + audit + artifacts + evidence | ClickHouse Cloud -- 7 tables: `cfp`, `arxiv`, `trace_log`, `session_artifacts`, `user_profile`, `outreach_log`, `o1_evidence` | **ClickHouse** |
| Multi-user auth | passcode shim (`paperpilot/auth.py`); example users from `PAPERPILOT_USERS_JSON` env var; swap-in target is Clerk | (post-hack) |
| PDF dossier export | `reportlab` -- cover + summary + per-criterion sections with drafted narratives | (post-hack) |
| Citation trajectory chart | `plotly` -- cumulative `by_year` parsed from live Scholar HTML | (post-hack) |
| Live web data | `/v1/search` + `/v1/search?include_answer` + `/v1/extract` | **Nimble** |
| Brand + tone KB | `/org/brand-kit` + `/org/kb/raw` + `/org/search/context` + `/org/content-generation` | **Senso** |
| LLM observability | Lapdog local + Datadog LLM Observability cloud (`DD_LLMOBS_AGENTLESS_ENABLED=1`) | **Datadog** |
| Cost + token accounting | `tiktoken` fallback + per-model price table, `cost_source: gateway\|estimated` | (observability) |
| Citation grounding | arxiv corpus pre-filter + post-hoc regex strip | (anti-hallucination) |
| Deployment | Railway (Nixpacks builder, Streamlit on `$PORT`) | (infra) |

---

## Observability

Every LLM call in Merit is wrapped by `trace.step(...)` in `paperpilot/trace.py`, which records a `.start` and `.end` event into:

- An **in-process buffer** keyed by `session_id`, drained by the Streamlit right rail.
- **ClickHouse** `trace_log` table (best-effort; never fails the user-facing run).
- **Lapdog** locally + **Datadog LLM Observability** when `DD_LLMOBS_AGENTLESS_ENABLED=1` is set.

Each `.end` event payload carries `tokens_in`, `tokens_out`, `cost_usd`, `dur_ms`, and a `cost_source: "gateway" | "estimated"` discriminator.

### Cost + token capture

We learned mid-build that the Vercel AI Gateway does not reliably propagate `usage` on streamed Anthropic responses — even with `stream_options={"include_usage": True}` set. So `paperpilot/draft.py` implements a graceful fallback:

1. Prefer real `usage.prompt_tokens` / `usage.completion_tokens` / `usage.cost` from the final stream chunk when the Gateway returns it.
2. Fall back to a local `tiktoken` (cl100k_base) count of `sys_prompt + user_prompt` for input tokens, and the accumulated stream for output tokens.
3. Estimate cost from a small per-million-token price table (`_PRICE_PER_MTOK`) keyed by model prefix.
4. Tag every event with `cost_source` so the UI pill can show `(est.)` honestly when estimation was used.

The session pill at the top of the Agent trace panel sums `tokens_in`, `tokens_out`, and `cost_usd` across every `.end` event in the current session — including ingest, citation candidates, venue match, and all four drafted sections. A full nanoGPT-scale run costs roughly **$0.01** end-to-end.

### Session artifact persistence

Every generated artifact (LaTeX paper, BibTeX, Claude Code plugin zip) is written to ClickHouse's `session_artifacts` table, tagged by `session_id`, `repo`, and `venue`. The right-rail "Past sessions" panel pulls the most recent 10 rows on every render so judges can replay any prior run, see the size of each artifact, and re-download from ClickHouse without re-running the pipeline. Plugin zips are stored base64-encoded (the `content` column is `String`); tex/bib are stored as plain UTF-8. Writes are best-effort with structured `artifact.<kind>.save_failed` trace events on failure -- the user-facing download is never blocked by a ClickHouse outage.

### Live web data (Nimble)

`paperpilot/nimble_client.py` wraps three Nimble SDK endpoints (`/v1/search`, `/v1/search` with `include_answer: true`, `/v1/extract`) behind a 5-8s timeout and `trace.step` instrumentation. Three surfaces in the UI use it:

- **Venue discovery (critical path, `cfp_match.py:_nimble_candidate_venues`).** Nimble Search runs alongside the ClickHouse cosine-distance ranking and contributes up to 3 live web venues into the candidate pool. Each hit is embedded and scored with the same formula as curated venues so they compete fairly. UI venue cards carry a `LIVE · Nimble` or `Curated` badge.
- After ingest, the chosen venue card exposes a **Live web check** that runs Search (top hits for `<venue> <year> deadline`) + Extract (the CFP page itself) to validate the curated `data/cfp_seed.json` against live web reality.
- After plugin extraction, **Check prior art** runs Nimble Answers ("are there existing Claude Code plugins / MCP servers that do this?") so the user can see ecosystem overlap before publishing.

Set `NIMBLE_API_KEY` to enable; without it the buttons hide, venue ranking falls back to ClickHouse-only, and the sponsor wire shows `off`. All Nimble calls show up in the trace panel under the orange `nimble.*` color.

---

## Authentication

Merit was multi-tenant-hardened post-hackathon. Every Streamlit page is gated by `paperpilot.auth.require_auth()`, which renders a passcode form and blocks the rest of the page render until the user signs in. After a successful sign-in, `st.session_state["user_id"]` and `st.session_state["user_name"]` are populated; the sidebar shows the signed-in user with a sign-out button.

Configure users via the `PAPERPILOT_USERS_JSON` env var:

```bash
PAPERPILOT_USERS_JSON='[{"user_id":"user1","name":"Ada Lovelace","passcode":"..."},{"user_id":"user2","name":"Alan Turing","passcode":"..."}]'
```

If the env var is unset, empty, or invalid JSON, the module fails closed and grants access to nobody, surfacing an `st.error` on the login screen. Set `ALLOW_DEV_AUTH=1` to opt back into a single built-in dev user (`dev` / `dev`) for local development; an `st.warning` marks the degraded state.

`user_id` threads through every write: `trace.new_session(user_id)`, `pipeline.save_artifact(user_id, ...)`, `clickhouse_client.fetch_artifacts(user_id, ...)`, `outreach.orchestrator.generate_drafts(..., user_id=...)`, and the O-1A evidence ledger. The past-sessions panel on Productize, the outreach drafts on Market, and the evidence ledger on Track are all scoped to the signed-in user.

The auth shim is intentionally minimal and is a swap-in target for Clerk on Vercel Marketplace when the user count grows past two.

### Web app auth (Next.js, `web/`)

The `web/` frontend uses real Supabase Auth (email + password), not the passcode shim above. Relevant routes, all under `web/app/(auth)/`:

- `/login`, `/signup` -- standard sign in / sign up.
- `/forgot-password` -- collects an email and calls `supabase.auth.resetPasswordForEmail`. Always shows the same "check your email" confirmation regardless of whether the account exists, to avoid leaking which emails are registered.
- `/reset-password` -- the page the emailed recovery link lands on. supabase-js exchanges the link's token for a session client-side (listened for via `onAuthStateChange`); once that resolves, the user sets a new password via `supabase.auth.updateUser`.

**Redirect URL allowlist (read this before testing password reset on a new environment).** `resetPasswordForEmail` is called with `redirectTo: ${window.location.origin}/reset-password`, but Supabase silently ignores any `redirectTo` that isn't on the project's allowlist and falls back to the configured Site URL instead (commonly `localhost:3000` left over from local dev) -- the emailed link will send you to your laptop instead of the deployment you tested from. Fix it in the Supabase dashboard -> **Authentication -> URL Configuration -> Redirect URLs**, and add:

```
https://merit-ai-git-develop-andre-chuabios-projects.vercel.app/**
https://merit-ai-git-*-andre-chuabios-projects.vercel.app/**   # every branch preview
https://<your-production-domain>/**
```

See `DEPLOYMENT.md` for the branch-preview URL scheme these patterns match.

---

## Migrations

Schema lives in two places, with the migrations folder as the source of truth for existing deployments:

- `paperpilot/clickhouse_client.py::SCHEMA_SQL` -- `CREATE TABLE IF NOT EXISTS` strings for every table, run by `init_schema()` at Streamlit boot. Provisions a fresh deploy.
- `migrations/*.sql` -- one file per additive change against an existing cluster (column adds, new tables). Idempotent (`IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`).

Run all pending migrations against the configured ClickHouse with:

```bash
uv run python scripts/run_migrations.py
```

The runner reads every `.sql` file in lexicographic order, strips SQL comments, splits on `;`, and runs each statement. Safe to re-run.

| File | What it does |
|------|--------------|
| `0002_add_user_id.sql` | Adds `user_id String DEFAULT ''` to `trace_log` and `session_artifacts`. Existing rows backfill to `''` and become invisible to user-scoped reads (the intended privacy behavior). |
| `0003_add_o1_evidence.sql` | Creates the `o1_evidence` table (ReplacingMergeTree by `updated_at`, ordered by `user_id, criterion, id`, soft-delete via tombstone column). |

`init_schema()` fires once per session from `Productize.py`. If you navigate directly to a sub-page URL on a fresh cluster, the schema may not be provisioned yet -- run the migrations script before first use.

---

## Quickstart

This section covers the legacy Streamlit surface (`make dev`). For the primary FastAPI + Next.js surface, see "Run it" at the top of this file -- it needs only `AI_GATEWAY_API_KEY` plus Supabase, not ClickHouse.

```bash
# 0. Prereqs: macOS, uv, brew, gh CLI.

# 1. Install dependencies
uv sync
brew install datadog/lapdog/lapdog

# 2. Configure
cp .env.example .env
# Required: AI_GATEWAY_API_KEY, CLICKHOUSE_HOST/USER/PASSWORD
# Required for auth: PAPERPILOT_USERS_JSON (see Authentication section)
# Recommended: DD_API_KEY + DD_SITE + DD_LLMOBS_ENABLED=1 + DD_LLMOBS_ML_APP for cloud forward
# Recommended: NIMBLE_API_KEY for live venue discovery + verification + prior-art
# Recommended: SENSO_API_KEY for brand-kit + tone KB + outreach drafting

# 3. Seed corpora + apply migrations
make seed                                # CFP + arxiv embeddings into ClickHouse
make seed-senso                          # tone exemplars into Senso KB
uv run python scripts/run_migrations.py  # additive schema for user_id + o1_evidence

# 4. Launch
make dev
# -> http://localhost:8501  (Streamlit UI)
# -> http://localhost:8126  (Lapdog local)
# -> https://lapdog.datadoghq.com (Lapdog browser dashboard, reads from :8126)
# -> Datadog LLM Observability cloud (when DD_LLMOBS_AGENTLESS_ENABLED=1)
```

### Production deploy (Railway)

The repo includes `railway.toml` + `nixpacks.toml` + `scripts/railway_env_setup.sh`:

```bash
railway login
railway init --name paperpilot
make railway-env       # pushes every .env var (with --skip-deploys) + auto-sets DD_LLMOBS_AGENTLESS_ENABLED=1
make railway-deploy    # railway up --detach
```

Live URL is printed by `railway domain` (or generated automatically). The production container ships LLM traces to Datadog cloud directly via the agentless ddtrace mode since Lapdog is macOS-only.

**Before first prod sign-in:**

1. Set `PAPERPILOT_USERS_JSON` in the Railway service env vars with real passcodes (not the local placeholders). Railway auto-redeploys on env var change.
2. Run `uv run python scripts/run_migrations.py` against production ClickHouse (the migrations are idempotent and additive -- safe to re-run).

### Three pages in the live app

- **Productize** (`Productize.py`). Paste a GitHub URL (or click a chip: nanoGPT, transformers, llama.cpp, Merit). Ingest -> match -> draft -> export `.tex/.bib`. "Extract plugin" runs the Claude Code plugin extractor on the same bundle. "Load demo cache" replays a precomputed `data/demo_cache.json` with a 6-second synthetic event drip (Wi-Fi-failure insurance). Past-sessions panel and saved artifacts are scoped to the signed-in user.
- **Market** (`pages/Market.py`). Personal Brand / Generate Content / Search People / Blast tabs over a Senso brand-kit. Profile load is gated to the signed-in user (closed the resume-leak vector from the hackathon build).
- **Track** (`pages/Track.py`). Headline "X of 8 O-1A criteria satisfied" with status pills, Evidence Ledger tab for declaring per-criterion items, "Draft narrative" buttons that stream petition-quality paragraphs via the AI Gateway, "Build O-1A dossier (PDF)" two-step download via reportlab, Scholar mock-fallback transparency banner, and the heuristic gauges demoted to "not USCIS-official" on the Dashboard tab.

`make ping` runs a CLI hello-world. `make precompute URL=...` refreshes the demo cache. `make meta` runs Merit on its own repo to regenerate `submission/paperpilot.tex`.

---

## Project structure

```
agentichack/
  Productize.py                   Streamlit entry: repo -> paper -> plugin
  pages/
    Market.py                       Senso brand kit + outreach drafting (4 tabs)
    Track.py                        O-1A evidence ledger + narrative drafter + PDF dossier

  paperpilot/
    auth.py                       passcode shim, require_auth(), sign_out()
    ui.py                         shared dark-theme component library
                                  (sidebar_brand, hero, section_heading,
                                   trace_event, metric_tile, venue_card,
                                   evidence_tile)
    github_ingest.py              PyGithub repo -> ranked file bundle
    llm_ingest.py                 Gemini 1M-ctx -> structured ResearchSummary
    embed.py                      text-embedding-3-small via Gateway
    cfp_match.py                  cosineDistance venue ranking + Nimble live merge
    arxiv_lookup.py               citation candidate pre-filter (ClickHouse + arxiv)
    draft.py                      section streaming + Senso tone + citation strip + tiktoken/cost fallback
    skill_extract.py              repo bundle -> structured PluginPack via Gemini
    skill_render.py               PluginPack -> Claude Code plugin directory zip
    nimble_client.py              Search / Answers / Extract HTTPS client
    senso_client.py               KB ingest + search_context (tone retrieval for Productize)
    clickhouse_client.py          schema + trace_log + session_artifacts + o1_evidence
    latex_export.py               .tex + .bib assembly
    pipeline.py                   end-to-end orchestrator + demo cache + save_artifact (user_id-scoped)
    trace.py                      log_event + step context manager + in-process buffer (user_id-scoped)
    gateway.py                    Vercel AI Gateway client
    llm_ping.py                   Phase 1 hello-world helper
    outreach/                     Market + Track logic
      senso.py                      Senso brand-kit + content-types + content-generation
      log.py                        UserProfile + draft log (ClickHouse-backed, user-keyed)
      orchestrator.py               generate_drafts orchestration (user_id-required)
      purpose.py                    VISA / SPEAKING / COLLAB / NETWORK enum + prompts
      scholar.py                    Google Scholar fetch with mock-fallback transparency
                                    + cumulative by_year derivation
      content_types.py              Senso content-type seed helpers
      github_repos.py               Find people via GitHub for outreach search
      evidence.py                   O-1A evidence ledger CRUD (8 USCIS criteria)
      evidence_draft.py             per-criterion narrative streaming via AI Gateway
      dossier.py                    reportlab PDF dossier export

  migrations/
    0002_add_user_id.sql          ALTER ADD COLUMN user_id (additive)
    0003_add_o1_evidence.sql      CREATE TABLE o1_evidence

  .streamlit/
    config.toml                   dark theme + base/primary/bg colors

  data/
    cfp_seed.json                 41 hand-curated CFPs
    arxiv_seed.json               223 arxiv papers
    demo_cache.json               precomputed pipeline output for offline demo

  scripts/
    seed_clickhouse.py            embed + insert CFP + arxiv corpora
    seed_senso.py                 ingest tone exemplars into Senso KB
    fetch_arxiv.py                refresh the arxiv corpus
    refresh_cfp_corpus.py         Nimble -> ClickHouse cfp batch refresh (up to 20 venues)
    demo_precompute.py            DEMO_MODE cache writer
    meta_flex.py                  run the agent on this repo itself
    railway_env_setup.sh          push .env into the linked Railway service
    run_migrations.py             apply every migrations/*.sql against the configured ClickHouse

  submission/
    paperpilot.tex                meta-flex paper draft (Merit on Merit)
    references.bib                BibTeX for paperpilot.tex
    summary.json                  structured ResearchSummary from meta_flex
    demo_script.md                90s / 60s / 30s pitch + Q&A + fallbacks
    linkedin_post.md              post-hackathon LinkedIn drafts

  railway.toml + nixpacks.toml    Railway deploy config
  Makefile                        dev / seed / ping / precompute / meta / refresh-corpus /
                                  railway-env / railway-deploy / push
```

---

## Citation grounding

Two layers of defense against hallucinated citations in the related-work section:

1. **Candidate pre-filter (ClickHouse).** Embed the repo summary, fetch the top-10 closest arxiv IDs from the corpus by cosine distance. Only those IDs appear in the prompt; the model is instructed to cite ONLY from that list.
2. **Post-hoc strip.** After streaming, regex `\[arxiv:([^\]]+)\]` scans the output; any ID not in the approved set is removed and surfaced in the UI as a "stripped N unapproved citations" warning. Surviving citations are resolved through the in-process `_CACHE` first, falling back to the live arxiv API for BibTeX enrichment.

Result: zero hallucinated citations make it into the final paper. The visible warning when the model attempts an unsanctioned cite is itself a feature — judges can see the gate firing.

---

## The meta-flex

At 16:25 we run Merit on the Merit repo itself:

```bash
make meta
# -> submission/paperpilot.tex
# -> submission/references.bib
# -> submission/summary.json
```

That paper draft ships with the Devpost.

---

## Team

- **Andre Chuabio** ([@AndreChuabio](https://github.com/AndreChuabio)) — engineering: agentic pipeline (Productize), observability, deploy
- **Nikki** — outreach + immigration-track workflow (Market + Track), Senso brand kit, demo-tone review

Built at the **Agentic Engineering Hack NYC** at **Datadog HQ**, 2026-05-23. Sponsors: **Vercel AI Gateway**, **Anthropic**, **DeepMind**, **ClickHouse**, **Nimble**, **Senso**, **Datadog**, **Luminai**.

Live: https://paperpilot-production-97dc.up.railway.app · Code: https://github.com/AndreChuabio/agentichack
