"""Ingest router: turn a GitHub repo into a structured ResearchSummary.

Exposes POST /ingest. The caller supplies a repo URL; the endpoint bundles
the repo, summarizes it through the existing LLM ingestion pipeline, and
returns the ResearchSummary alongside repo metadata and a generated session
id. Auth is required; the authenticated user scopes the durable ingest trace.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend import quotas
from backend.auth import AuthUser, CurrentUser
from backend.byok import RequireLLMKey
from backend.services.ingest_service import ingest_repo
from paperpilot import vertex
from paperpilot.llm_ingest import ResearchSummary

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    """Body for POST /ingest."""

    repo_url: str
    # When the bundle estimate is above ingest_service.MAX_UNCONFIRMED_TOKENS,
    # the first call is refused with a 413 telling the caller the estimate.
    # Re-sending with confirm_large=True proceeds -- this runs on the
    # caller's own API key, so an oversized run is opt-in, not automatic.
    confirm_large: bool = False


class IngestResponse(BaseModel):
    """The structured summary plus repo and session metadata."""

    session_id: str
    owner: str
    name: str
    file_count: int
    summary: ResearchSummary


@router.post("", response_model=IngestResponse)
def ingest(
    req: IngestRequest,
    user: AuthUser = CurrentUser,
    _: None = RequireLLMKey,
) -> IngestResponse:
    """Ingest a GitHub repo and return its ResearchSummary.

    Parses the repo, bundles a token-capped sample of files, and summarizes
    it via the LLM ingestion pipeline. A new session id is generated and an
    ingest trace is written best-effort scoped to the authenticated user.
    """
    repo_url = req.repo_url.strip()
    if not repo_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="repo_url is required",
        )

    # On the first-party Vertex path the generation runs on Merit's GCP
    # project regardless of the caller's X-LLM-Key, so it needs the same
    # admission cap as every other Merit-funded surface. The gateway path
    # spends the caller's own key and stays uncapped.
    if vertex.vertex_enabled():
        quotas.admit_always(user.id, quotas.INGEST)

    try:
        result = ingest_repo(repo_url, user.id, confirm_large=req.confirm_large)
    except ValueError as exc:
        # Unparseable repo URL from github_ingest._parse_repo_url.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except HTTPException:
        # Raised deliberately by ingest_repo (e.g. check_bundle_size's 413) --
        # let it through as-is instead of masking it as a generic 502 below.
        raise
    except Exception as exc:  # noqa: BLE001 -- surface a clean 502 to the caller
        _log.exception("ingest failed for %s", repo_url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ingest failed: {exc!s}",
        ) from exc

    return IngestResponse(
        session_id=result.session_id,
        owner=result.owner,
        name=result.name,
        file_count=result.file_count,
        summary=result.summary,
    )
