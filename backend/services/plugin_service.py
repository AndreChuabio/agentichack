"""Plugin extraction service.

Wraps the existing paperpilot plugin pipeline (github_ingest -> skill_extract
-> skill_render) and persists the rendered Claude Code plugin zip to
session_artifacts. No LLM logic lives here; it is delegated to
paperpilot.skill_extract.extract_plugin.

Bundle reuse: /ingest already fetches and renders the repo bundle for a
session and stores it as a "repo_bundle" artifact (see ingest_service.py).
When /extract-plugin is called with that same session_id, it reads the
stored bundle instead of re-fetching from GitHub and re-assembling it --
that fetch-and-render pass, on a large repo, is real work done on the user's
behalf and there is no reason to pay for it twice. A plugin-only run (no
prior /ingest call in the session) still works: with nothing cached, it
falls back to a fresh fetch.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status

from paperpilot import supabase_client
from paperpilot.github_ingest import _parse_repo_url, fetch_repo, render_bundle
from paperpilot.skill_extract import PluginPack, extract_plugin
from paperpilot.skill_render import build_plugin_zip, render_plugin_manifest


def fetch_repo_bundle(repo_url: str, token_cap: int | None = None) -> str:
    """Fetch a repo from GitHub and render it into the text sent to the LLM.

    Wraps github_ingest.fetch_repo + render_bundle so callers (and tests) can
    treat "get me the bundle text for this repo" as one step, regardless of
    whether it is served from cache or fetched fresh.

    ``token_cap`` overrides the 600K default for callers that read several repos
    into one prompt. Plugin extraction reads one repo and wants everything;
    a portfolio site reads up to eight and only needs enough to describe each,
    and eight full bundles would be ~4.8M tokens -- past the model's context
    window, so the call fails outright rather than merely costing a fortune.
    """
    if token_cap is None:
        return render_bundle(fetch_repo(repo_url))
    return render_bundle(fetch_repo(repo_url, token_cap=token_cap))


def _load_bundle(session_id: str, user_id: str, repo_url: str) -> str:
    """Return the repo bundle text for this session, fetching only if not cached.

    /ingest already fetched, rendered, and paid for this bundle when it ran
    in this session. Re-fetching and re-rendering it here would double the
    GitHub calls and the bundle-assembly cost of a Productize run for no
    benefit. Only a plugin-only run (no prior /ingest in this session) falls
    back to fetching fresh.
    """
    cached = supabase_client.fetch_artifact_content(
        session_id, "repo_bundle", user_id=user_id
    )
    if cached:
        return cached
    return fetch_repo_bundle(repo_url)


def _check_session_ownership(session_id: str, user_id: str) -> None:
    """Reject a caller-supplied session_id that already belongs to another user.

    Reads are naturally safe: fetch_artifact_content filters by user_id, so
    a caller who passes another user's session_id just gets no cached
    bundle and falls back to fetching fresh (see _load_bundle). Writes are
    not -- trace.step (inside extract_plugin) and insert_artifact below
    would happily write rows keyed to that other user's session_id
    namespace. An unknown session_id (no existing owner) is a fresh session
    and is allowed through.
    """
    owner_id = supabase_client.session_owner(session_id)
    if owner_id is not None and owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="session_id belongs to a different user",
        )


@dataclass(frozen=True)
class PluginResult:
    """Outcome of a plugin extraction: name, manifest dict, and zip bytes."""

    plugin_name: str
    manifest: dict
    zip_bytes: bytes


def extract_plugin_from_repo(
    repo_url: str, user_id: str, session_id: str | None = None
) -> PluginResult:
    """Fetch a repo, extract a PluginPack, render the plugin zip, and persist it.

    The repo bundle feeds a single Gateway LLM call (in extract_plugin) that
    returns a structured PluginPack, which skill_render turns into an on-disk
    Claude Code plugin layout zipped in memory. The zip is base64-encoded and
    written to session_artifacts as a "plugin" artifact, scoped to the caller.

    Persistence is best-effort: a Supabase write failure must not block the
    user-facing download, matching the convention in insert_artifact.

    Args:
        repo_url: GitHub repository URL to extract the plugin from.
        user_id: Supabase auth UUID of the authenticated caller.
        session_id: The session id from a prior /ingest call on this same
            repo, if any. When given, the bundle stored by that ingest is
            reused instead of re-fetched. When absent (a plugin-only run
            with no prior ingest), a fresh session id is generated and the
            bundle is fetched fresh.

    Returns:
        A PluginResult with the kebab-case plugin name, the parsed manifest,
        and the raw zip bytes for the caller to base64-encode for the response.

    Raises:
        HTTPException(403): session_id was supplied and already belongs to
            a different user_id.
    """
    if session_id is not None:
        _check_session_ownership(session_id, user_id)
    session_id = session_id or str(uuid.uuid4())
    source_repo = repo_url.strip()
    owner, name = _parse_repo_url(source_repo)
    source_label = f"{owner}/{name}"

    rendered = _load_bundle(session_id=session_id, user_id=user_id, repo_url=source_repo)
    pack: PluginPack = extract_plugin(rendered, session_id, repo_label=source_label)

    zip_bytes = build_plugin_zip(pack, source_label)
    manifest = json.loads(render_plugin_manifest(pack, source_label))
    plugin_name = manifest["name"]

    zip_b64 = base64.b64encode(zip_bytes).decode("ascii")
    content_hash = hashlib.sha256(zip_bytes).hexdigest()

    try:
        supabase_client.insert_artifact(
            session_id,
            user_id,
            "plugin",
            f"{plugin_name}.zip",
            zip_b64,
            repo=source_label,
            metadata={
                "repo_url": source_repo,
                "plugin_name": plugin_name,
                "encoding": "base64",
                "total_artifacts": pack.total_artifacts,
                "counts": {
                    "skills": len(pack.skills),
                    "commands": len(pack.commands),
                    "agents": len(pack.agents),
                    "hooks": len(pack.hooks),
                    "mcps": len(pack.mcps),
                },
            },
            content_hash=content_hash,
        )
    except Exception:  # noqa: BLE001 -- persistence must not block the download
        pass

    return PluginResult(
        plugin_name=plugin_name,
        manifest=manifest,
        zip_bytes=zip_bytes,
    )
