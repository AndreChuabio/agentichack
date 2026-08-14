"""Merit FastAPI backend.

First Phase 2 slice: health, identity, and venue matching over Supabase.
Ingest / draft / evidence / outreach endpoints follow in subsequent slices.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

# Unconfigured stdlib logging drops every logger.info in the app -- including
# the only record of a successful payment. Configure the root logger before
# anything else so payment and quota events actually reach the Railway logs.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Before any backend import, deliberately. Modules imported below may read
# configuration at import time, and a load_dotenv() that runs after them hands
# those reads an empty environment -- which is how a dotenv-driven deploy ended
# up with the paywall enabled and the billing endpoints 503ing, since
# entitlements reads env at call time and billing did not.
load_dotenv()

from fastapi import FastAPI, Response, status  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backend.auth import AuthUser, CurrentUser  # noqa: E402
from backend import quotas  # noqa: E402
from backend.byok import OptionalLLMKey  # noqa: E402
from backend.routers import (  # noqa: E402
    account,
    assist,
    billing,
    cfp,
    draft,
    evidence,
    export,
    ingest,
    market,
    plugin,
    site,
)
from backend.venues import rank_venues  # noqa: E402
from paperpilot import redaction, supabase_client  # noqa: E402
from paperpilot.llm_ingest import ResearchSummary  # noqa: E402

# Bumped on every deploy that changes behaviour. Reported by /health so a
# rollout can be confirmed rather than assumed.
BUILD = "0.3.3-publish-restore"

app = FastAPI(title="Merit API", version=BUILD)

redaction.install()

# CORS for the Next.js frontend. Explicit origins (localhost + the production
# domain) come from FRONTEND_ORIGINS; the regex additionally allows every
# Vercel preview deploy (per-PR URLs like web-<hash>-<scope>.vercel.app) so
# preview environments work without re-listing each ephemeral URL.
_origins = [
    o.strip()
    for o in os.environ.get("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
_vercel_preview_regex = os.environ.get(
    "FRONTEND_ORIGIN_REGEX", r"https://.*\.vercel\.app"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=_vercel_preview_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Feature routers. Core routes (/health, /me, /match) stay defined inline below.
app.include_router(ingest.router)
app.include_router(draft.router)
app.include_router(export.router)
app.include_router(plugin.router)
app.include_router(site.router)
app.include_router(evidence.router)
app.include_router(market.router)
app.include_router(assist.router)
app.include_router(cfp.router)
app.include_router(account.router)
app.include_router(billing.router)


class HealthResponse(BaseModel):
    """Liveness, database reachability, and which build is answering.

    ``build`` exists because a deploy that changes only behaviour -- a
    dependency becoming optional, a cap being added -- leaves no trace in the
    OpenAPI schema, so there was no way to tell from outside whether a rollout
    had actually landed. Guessing at that during an incident is how a fix gets
    redeployed three times before anyone notices it shipped the first time.
    """

    status: str
    database: bool
    build: str


class VenueResponse(BaseModel):
    id: str
    name: str
    scope: str
    deadline: str
    url: str
    fit_score: float
    days_until_deadline: int


class MatchRequest(BaseModel):
    summary: ResearchSummary
    limit: int = 5
    horizon_days: int = 365


class MeResponse(BaseModel):
    id: str
    email: str | None


@app.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    """Liveness probe. Reports whether the Supabase connection is reachable.

    Returns 503 when the database is unreachable so an external status-code
    probe actually goes red; the body keeps the same shape either way.
    """
    db_ok = False
    try:
        conn = supabase_client.get_conn()
        try:
            conn.execute("SELECT 1")
            db_ok = True
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 -- health must never raise
        db_ok = False
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if db_ok else "degraded", database=db_ok, build=BUILD)


@app.get("/me", response_model=MeResponse)
def me(user: AuthUser = CurrentUser) -> MeResponse:
    """Return the authenticated caller (proves the auth wire end-to-end)."""
    return MeResponse(id=user.id, email=user.email)


@app.post("/match", response_model=list[VenueResponse])
def match(
    req: MatchRequest,
    user: AuthUser = CurrentUser,
    _: None = OptionalLLMKey,
) -> list[VenueResponse]:
    """Rank open CFP venues for a research summary via Supabase pgvector."""
    # One embedding of a short summary: cents per thousand calls, so Merit
    # absorbs it rather than making the surface unusable without a key.
    quotas.admit(user.id, quotas.MATCH)
    matches = rank_venues(req.summary, limit=req.limit, horizon_days=req.horizon_days)
    return [
        VenueResponse(
            id=m.id,
            name=m.name,
            scope=m.scope,
            deadline=m.deadline.isoformat() if m.deadline else "",
            url=m.url,
            fit_score=round(m.fit_score, 4),
            days_until_deadline=m.days_until_deadline,
        )
        for m in matches
    ]
