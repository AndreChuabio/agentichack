"""Publish router.

Exposes POST /publish/site: build a static portfolio site from the caller's
profile, the repos they picked, and the evidence they explicitly chose to
publish. Returns the site zip base64-encoded for download.

Gating is wired from day one but ships dark: has_entitlement returns True while
STRIPE_PRICE_PORTFOLIO is unset, so switching the paywall on later is an env var
rather than a code change.
"""

from __future__ import annotations

import base64
import json
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from backend import quotas
from backend.auth import AuthUser, CurrentUser
from backend.byok import RequireLLMKey
from backend.entitlements import PORTFOLIO, has_entitlement
from backend.services.site_service import build_site

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
    """The built site: name, resolved theme, preview HTML, and the zip."""

    site_name: str
    theme: dict
    html_preview: str
    zip_base64: str
    skipped: list[SkippedRepo]


@router.post("/publish/site", response_model=BuildSiteResponse)
def build_site_endpoint(
    req: BuildSiteRequest,
    user: AuthUser = CurrentUser,
    _: None = RequireLLMKey,
) -> BuildSiteResponse:
    """Build a portfolio site and return it zipped."""
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
    )
