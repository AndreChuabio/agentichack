"""Portfolio site build service.

Orchestrates profile + repo bundles + explicitly chosen evidence into a
rendered static site zip, and persists it to session_artifacts.

The governing privacy rule lives here: the build includes exactly the
evidence_ids in the request and never widens that set. Nothing reads a stored
publish flag to decide inclusion, so a flag left over from an earlier build can
never republish an item the user later thought better of. Every requested id is
checked against the caller before it is read, because otherwise guessing a uuid
would publish another user's case material.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass

from fastapi import HTTPException, status

from backend.services.evidence_service import list_evidence
from backend.services.market_service import get_profile
from backend.services.plugin_service import (
    _check_session_ownership,
    _load_bundle,
    fetch_repo_bundle,
)
from backend.services.publish_target import HostedTarget
from paperpilot import supabase_client, trace
from paperpilot.github_ingest import _parse_repo_url
from paperpilot.site_extract import build_pack
from paperpilot.site_models import resolve_layout, resolve_palette, site_slug
from paperpilot.site_render import build_site_zip, render_index_html

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteResult:
    """One built site: name, resolved theme, preview, zip, and what was dropped.

    ``public_url`` is the address the site WOULD answer on. It is not live
    until the user takes the separate publish action, because the build files
    the render as a draft.
    """

    site_name: str
    theme: dict
    html_preview: str
    zip_bytes: bytes
    skipped: list[dict]
    slug: str = ""
    public_url: str = ""


def _profile_dict(user_id: str) -> dict[str, str]:
    """The caller's profile as plain strings for the prompt."""
    profile = get_profile(user_id)
    return {
        "name": profile.name,
        "title": profile.title,
        "about": profile.about,
        "voice_tone": profile.voice_tone,
        "github_url": profile.github_url,
        "linkedin_url": profile.linkedin_url,
        "scholar_url": profile.scholar_url,
        "site_url": profile.site_url,
    }


def _selected_evidence(user_id: str, evidence_ids: list[str]) -> list[dict[str, str]]:
    """The requested evidence rows, once every one is proved to be the caller's.

    Rejects rather than silently dropping: a caller who asked to publish an id
    they do not own has either a bug or bad intent, and quietly building a site
    without it would tell them neither.
    """
    if not evidence_ids:
        return []
    owned = {str(item.id): item for item in list_evidence(user_id)}
    missing = [eid for eid in evidence_ids if eid not in owned]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="one or more evidence_ids do not belong to the caller",
        )
    selected = []
    for eid in evidence_ids:
        item = owned[eid]
        selected.append(
            {
                "criterion": item.criterion,
                "title": item.title,
                "description": item.description,
                "url": item.evidence_url,
                "date": item.evidence_date.isoformat() if item.evidence_date else "",
            }
        )
    return selected


def _bundles(
    repo_urls: list[str], *, session_id: str, user_id: str, reuse: bool
) -> tuple[list[tuple[str, str]], list[dict]]:
    """Fetch every repo bundle, collecting the ones that could not be fetched.

    A repo that fails costs its own card and nothing else. Failing the whole
    build over one unreachable repo would throw away the work already done on
    every other one.

    ``reuse`` reads the cached repo_bundle artifact a prior /ingest on this
    session already paid for, exactly as plugin_service._load_bundle does. It
    applies only to a single-repo build: that artifact is keyed by session and
    not by repo, so on a multi-repo site it would hand every project the same
    bundle. The caller decides rather than this function guessing.
    """
    repos: list[tuple[str, str]] = []
    skipped: list[dict] = []
    for repo_url in repo_urls:
        url = repo_url.strip()
        if not url:
            continue
        try:
            owner, name = _parse_repo_url(url)
            bundle = (
                _load_bundle(session_id=session_id, user_id=user_id, repo_url=url)
                if reuse
                else fetch_repo_bundle(url)
            )
            repos.append((f"{owner}/{name}", bundle))
        except Exception as exc:  # noqa: BLE001 -- one repo must not fail the build
            logger.warning("site build skipped repo %s: %s", url, exc)
            skipped.append({"repo_url": url, "reason": str(exc)[:200]})
    return repos, skipped


def build_site(
    *,
    user_id: str,
    repo_urls: list[str],
    evidence_ids: list[str],
    session_id: str | None = None,
) -> SiteResult:
    """Build one portfolio site zip for the caller.

    Raises:
        HTTPException(403): session_id belongs to another user, or an
            evidence_id does not belong to the caller.
    """
    supplied = session_id is not None
    if supplied:
        _check_session_ownership(session_id, user_id)

    # Bind the session to THIS caller before anything is logged against it. A
    # session id that was never registered resolves to no user binding at log
    # time, so trace_log.user_id is written NULL -- and a NULL-user row is
    # invisible to the quota's WHERE user_id = %s. That is exactly how a
    # caller-supplied session_id used to bypass the dossier quota indefinitely
    # (see the note in evidence_service.build_dossier).
    session_id = (
        trace.bind_session(session_id, user_id) if supplied else trace.new_session(user_id)
    )

    # The whole build runs inside one step so it emits a "site_build.end" event
    # on success, which is the row backend.quotas.SITE counts against. Without
    # it the 5-per-30-days cap reads zero forever and never trips, on a free
    # surface that spends an LLM call plus a GitHub fetch per repo.
    with trace.step(session_id, "site_build", user_id=user_id) as ctx:
        profile = _profile_dict(user_id)
        evidence = _selected_evidence(user_id, evidence_ids)
        repos, skipped = _bundles(
            repo_urls,
            session_id=session_id,
            user_id=user_id,
            reuse=supplied and len(repo_urls) == 1,
        )

        pack = build_pack(
            profile=profile, repos=repos, evidence=evidence, session_id=session_id
        )
        if not pack.name:
            pack.name = profile.get("name") or "portfolio"

        zip_bytes = build_site_zip(pack)
        preview = render_index_html(pack, inline_css=True)
        site_name = site_slug(pack.name)

        # Reserve the slug and file the render as a DRAFT. Nothing is world
        # readable until the user takes the separate publish action: unlike a
        # zip, which is inert until they run git push, a hosted URL would
        # otherwise be live the instant they clicked Generate. The draft stores
        # the same standalone HTML the preview shows, so it is reused here
        # rather than rendered a second time.
        target = HostedTarget()
        # One connection picks the slug and writes the draft, so the unique
        # index decides a collision rather than a probe that another build can
        # win between.
        slug = target.reserve_and_save(user_id, pack.name, preview)
        public_url = target.public_url(slug)

        # What was actually rendered, not what the model asked for. The
        # renderer resolves the theme independently, so reporting the raw value
        # would tell the client "neon" while the page it downloaded is slate.
        theme = {
            "palette": resolve_palette(pack.theme.palette).value,
            "layout": resolve_layout(pack.theme.layout).value,
        }
        ctx["projects"] = len(pack.projects)
        ctx["evidence"] = len(pack.evidence)
        ctx["skipped"] = len(skipped)

        try:
            supabase_client.insert_artifact(
                session_id,
                user_id,
                "portfolio_site",
                f"{site_name}.zip",
                base64.b64encode(zip_bytes).decode("ascii"),
                metadata={
                    "encoding": "base64",
                    "projects": len(pack.projects),
                    "evidence": len(pack.evidence),
                    "skipped": len(skipped),
                    "theme": theme,
                },
                content_hash=hashlib.sha256(zip_bytes).hexdigest(),
            )
        except Exception:  # noqa: BLE001 -- persistence must not block the download
            logger.exception("failed to persist portfolio site for user=%s", user_id)

    return SiteResult(
        site_name=site_name,
        theme=theme,
        html_preview=preview,
        zip_bytes=zip_bytes,
        skipped=skipped,
        slug=slug,
        public_url=public_url,
    )
