"""Propose profile fields from the links a user pasted.

Nothing here writes the profile. It returns proposals the user accepts field by
field, because silently overwriting an About paragraph somebody wrote by hand is
worse than not autofilling at all.

Sources fail independently and every failure is named. LinkedIn in particular
serves a login wall to automated fetches, so it is expected to fail often -- and
"LinkedIn could not be read" is a far more useful answer than an empty field
with no explanation.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.services.market_service import upsert_profile  # noqa: F401 -- see test
from paperpilot import nimble_client, trace
from paperpilot.gateway import DEFAULTS, get_client
from paperpilot.github_ingest import _gh_client, _owner_login

logger = logging.getLogger(__name__)

# Which profile URL field maps to which source label in the response.
_SOURCES: dict[str, str] = {
    "github_url": "github",
    "site_url": "site",
    "scholar_url": "scholar",
    "linkedin_url": "linkedin",
}

_BLOCKED_HINT = (
    "could not be read -- this source blocks automated fetching. "
    "Paste the text yourself or upload your resume instead."
)

# Fields the model is allowed to propose. Anything else it returns is dropped.
_PROPOSABLE = ("name", "title", "about", "voice_tone")

# How much of one fetched page is handed to the model.
_MAX_SOURCE_CHARS = 20000


@dataclass(frozen=True)
class SourceStatus:
    """Whether one pasted link could be read, and why not when it could not."""

    source: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class AutofillResult:
    """Proposed field values plus the per-source record of how they were got."""

    proposed: dict[str, str] = field(default_factory=dict)
    sources: list[SourceStatus] = field(default_factory=list)


def _github_bio(url: str) -> str:
    """The profile bio for a GitHub handle, or empty when it cannot be read."""
    try:
        user = _gh_client().get_user(_owner_login(url))
        return " ".join(x for x in (user.name or "", user.bio or "") if x).strip()
    except Exception as exc:  # noqa: BLE001 -- a dead source is a status, not a raise
        logger.info("github bio unavailable: %s", exc)
        return ""


def _propose(gathered: dict[str, str], session_id: str) -> dict[str, str]:
    """One LLM call turning whatever was gathered into proposed field values."""
    if not gathered:
        return {}
    prompt = "\n\n".join(f"## {k}\n{v}" for k, v in gathered.items() if v)
    if not prompt.strip():
        return {}
    client = get_client()
    completion = client.chat.completions.create(
        model=DEFAULTS["ingest"],
        messages=[
            {
                "role": "system",
                "content": (
                    "You are filling in a professional profile from material gathered "
                    "about one person. Return ONLY a JSON object with the keys name, "
                    "title, about, voice_tone. `about` is two or three short "
                    "paragraphs in the first person. Ground every claim in the "
                    "material; if something is not evidenced, leave that key as an "
                    "empty string rather than inventing it. Return text, never HTML."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=2000,
        temperature=0.3,
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match is None:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            logger.info("autofill proposal was not JSON: %s", exc)
            return {}
    if not isinstance(parsed, dict):
        return {}
    return {k: str(parsed.get(k) or "") for k in _PROPOSABLE if parsed.get(k)}


def _readable(payload: dict[str, Any] | None) -> str:
    """Whatever text a Nimble extract returned, or empty when it returned nothing.

    nimble_client.extract answers None on misconfiguration, timeout, or any
    non-2xx and never raises, so an unreachable or blocking source arrives here
    as None rather than as an exception.
    """
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data")
    if isinstance(data, str):
        return data[:_MAX_SOURCE_CHARS]
    if isinstance(data, dict):
        for key in ("text", "content", "markdown", "html"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value[:_MAX_SOURCE_CHARS]
    return ""


def autofill(user_id: str, urls: dict[str, str]) -> AutofillResult:
    """Read what can be read from the pasted links and propose field values.

    Runs inside a trace.step emitting profile_enrich.end on a session bound to
    the caller, which is the row backend.quotas.ENRICH counts. Without both the
    matching kind and the binding the quota reads zero forever.
    """
    session_id = trace.new_session(user_id)
    gathered: dict[str, str] = {}
    statuses: list[SourceStatus] = []

    with trace.step(session_id, "profile_enrich", user_id=user_id) as ctx:
        for field_name, label in _SOURCES.items():
            url = (urls.get(field_name) or "").strip()
            if not url:
                continue
            if label == "github":
                bio = _github_bio(url)
                gathered["github profile"] = bio
                statuses.append(
                    SourceStatus(label, bool(bio), "" if bio else "no public bio found")
                )
                continue
            payload = nimble_client.extract(url, session_id)
            text = _readable(payload)
            gathered[f"{label} page"] = text
            statuses.append(
                SourceStatus(label, bool(text), "" if text else f"{label} {_BLOCKED_HINT}")
            )
        proposed = _propose(gathered, session_id)
        ctx["sources_ok"] = sum(1 for s in statuses if s.ok)
        ctx["fields_proposed"] = len(proposed)

    return AutofillResult(proposed=proposed, sources=statuses)
