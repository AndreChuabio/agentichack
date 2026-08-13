"""Publish router.

Exposes POST /publish/site: build a static portfolio site from the caller's
profile, the repos they picked, and the evidence they explicitly chose to
publish. Returns the site zip base64-encoded for download. GET /publish/repos
feeds the picker those repos read off the caller's stored GitHub handle.

Gating is wired from day one but ships dark: has_entitlement returns True while
STRIPE_PRICE_PORTFOLIO is unset, so switching the paywall on later is an env var
rather than a code change.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from backend import quotas
from backend.auth import AuthUser, CurrentUser
from backend.entitlements import PORTFOLIO, has_entitlement
from backend.services.market_service import get_profile
from backend.services.publish_target import HostedTarget
from backend.services.site_service import build_site
from paperpilot.github_ingest import list_user_repos

logger = logging.getLogger(__name__)

router = APIRouter(tags=["publish"])

# A build costs one LLM call plus one GitHub fetch per repo. The cap is here so
# a client cannot turn one request into forty fetches.
MAX_REPOS = 8


class BuildSiteRequest(BaseModel):
    """Request body for a portfolio site build."""

    repo_urls: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    session_id: str | None = None


class SkippedRepo(BaseModel):
    """One repo that could not be fetched, and why."""

    repo_url: str
    reason: str


class BuildSiteResponse(BaseModel):
    """The built site: name, resolved theme, preview HTML, the zip, and where
    the hosted copy would answer once it is published."""

    site_name: str
    theme: dict
    html_preview: str
    zip_base64: str
    skipped: list[SkippedRepo]
    slug: str
    public_url: str


@router.post("/publish/site", response_model=BuildSiteResponse)
def build_site_endpoint(
    req: BuildSiteRequest,
    user: AuthUser = CurrentUser,
) -> BuildSiteResponse:
    """Build a portfolio site and return it zipped.

    No RequireLLMKey. A surface either runs on the caller's own gateway key
    (BYOK, uncapped) or on Merit's (capped) -- and this one is capped, by
    quotas.SITE below. Requiring both was contradictory, and in practice fatal:
    the web client sends no X-LLM-Key header on any request, so every call from
    the browser would have been refused with a 400 asking for a key the UI has
    no way to collect.
    """
    if len(req.repo_urls) > MAX_REPOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"at most {MAX_REPOS} repositories per site",
        )
    if not has_entitlement(user.id, PORTFOLIO):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Publish requires a purchase on this account",
        )
    quotas.enforce(user.id, quotas.SITE)

    try:
        result = build_site(
            user_id=user.id,
            repo_urls=req.repo_urls,
            evidence_ids=req.evidence_ids,
            session_id=req.session_id,
        )
    except HTTPException:
        # Raised deliberately downstream (403 on session or evidence ownership).
        # Let it through rather than masking it as a generic 502 below.
        raise
    except (json.JSONDecodeError, ValidationError) as exc:
        # A model that returned unparseable or wrong-shaped JSON is a pipeline
        # failure, not a bad request -- both of these are ValueError subclasses
        # and would otherwise be caught below and blamed on the caller. The
        # detail is deliberately fixed text: a ValidationError message embeds
        # the offending input, which here is unvalidated model output.
        logger.warning("site build got malformed model output: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Site build failed: the model returned malformed output",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001 -- surface pipeline errors as 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Site build failed: {exc}",
        ) from exc

    return BuildSiteResponse(
        site_name=result.site_name,
        theme=result.theme,
        html_preview=result.html_preview,
        zip_base64=base64.b64encode(result.zip_bytes).decode("ascii"),
        skipped=[SkippedRepo(**item) for item in result.skipped],
        slug=result.slug,
        public_url=result.public_url,
    )


class LiveUrlResponse(BaseModel):
    """Where the published site answers."""

    url: str


@router.post("/publish/site/live", response_model=LiveUrlResponse)
def go_live(user: AuthUser = CurrentUser) -> LiveUrlResponse:
    """Make the caller's built site public and return its URL.

    No RequireLLMKey: publishing spends no model call, it flips a flag on a
    render the build already paid for.
    """
    try:
        return LiveUrlResponse(url=HostedTarget().publish(user.id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete("/publish/site/live", status_code=status.HTTP_204_NO_CONTENT)
def take_down(user: AuthUser = CurrentUser) -> None:
    """Take the caller's site down and delete the stored HTML."""
    HostedTarget().unpublish(user.id)


class RepoOption(BaseModel):
    """One repo offered in the picker."""

    full_name: str
    html_url: str
    description: str
    language: str
    stars: int
    pushed_at: str
    fork: bool


class ReposResponse(BaseModel):
    """The caller's repos, plus whichever they picked last time."""

    repos: list[RepoOption]
    selected: list[str]


@router.get("/publish/repos", response_model=ReposResponse)
def list_repos(user: AuthUser = CurrentUser) -> ReposResponse:
    """List the caller's GitHub repos for the picker.

    Reads the handle off the stored Market profile so the user does not paste
    it twice. A profile with no GitHub URL is an empty list, not an error --
    the picker then simply has nothing to offer.

    No RequireLLMKey: listing repos spends no model call.
    """
    profile = get_profile(user.id)
    if not profile.github_url.strip():
        return ReposResponse(repos=[], selected=[])
    try:
        found = list_user_repos(profile.github_url)
    except Exception as exc:  # noqa: BLE001 -- a GitHub outage is not a 500 here
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read your GitHub repositories: {exc}",
        ) from exc
    return ReposResponse(
        repos=[RepoOption(**asdict(r)) for r in found],
        selected=list(profile.selected_repos or []),
    )
