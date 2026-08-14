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

from paperpilot import nimble_client, trace
from paperpilot.gateway import DEFAULTS, get_client
from paperpilot.github_ingest import _gh_client, _owner_login, list_user_repos

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

# How many repos describe someone before the list stops adding information.
_MAX_REPOS_SAMPLED = 30


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


@dataclass(frozen=True)
class _Fetched:
    """One source's material, and whether reading it actually succeeded.

    The two are separate on purpose. Empty text with ok=True means the source
    was read and had nothing; empty text with ok=False means it could not be
    read at all. Collapsing those is how a dead API token comes to be reported
    to the user as a fact about their own profile.
    """

    text: str
    ok: bool
    detail: str = ""


def _github_material(url: str) -> _Fetched:
    """The user's bio AND what they have actually built.

    The repos are the substantive half. A bio is one sentence somebody wrote
    once and often never; the repo list is evidence of what they work on, and it
    is what makes a proposed About specific rather than generic.

    A failure is reported as a failure. Returning empty for a 401, a rate limit,
    a misspelled handle and a genuinely empty account alike would tell the user
    "no public bio found" when the truth is their token is dead -- and leave
    them no reason to fix it.
    """
    try:
        user = _gh_client().get_user(_owner_login(url))
        parts = [x for x in (user.name or "", user.bio or "") if x]
    except Exception as exc:  # noqa: BLE001 -- a dead source is a status, not a raise
        logger.info("github profile unavailable: %s", exc)
        return _Fetched("", False, f"GitHub could not be read: {exc}"[:200])

    try:
        for repo in list_user_repos(url, limit=_MAX_REPOS_SAMPLED):
            line = repo.full_name
            if repo.language:
                line += f" [{repo.language}]"
            if repo.description:
                line += f" -- {repo.description}"
            parts.append(line)
    except Exception as exc:  # noqa: BLE001
        # The bio was read, so this is a partial success rather than a dead
        # source: say which half is missing instead of discarding both.
        logger.info("github repos unavailable: %s", exc)
        text = "\n".join(parts).strip()
        return _Fetched(text, bool(text), f"repositories could not be listed: {exc}"[:200])

    text = "\n".join(parts).strip()
    if not text:
        return _Fetched("", False, "this GitHub account has no bio and no public repositories")
    return _Fetched(text, True)


def _nimble_material(label: str, url: str, session_id: str) -> _Fetched:
    """One page read through Nimble, or the honest reason there is nothing.

    nimble_client.extract answers None on misconfiguration, timeout, or any
    non-2xx and never raises, so a blocking source arrives as None rather than
    as an exception to catch.
    """
    text = _readable(nimble_client.extract(url, session_id))
    if text:
        return _Fetched(text, True)
    return _Fetched("", False, f"{label} {_BLOCKED_HINT}")


def _propose(gathered: dict[str, str], session_id: str) -> dict[str, str]:
    """One LLM call turning whatever was gathered into proposed field values.

    Traced as `enrich.propose`, deliberately NOT under the `profile_enrich`
    prefix: quotas.ENRICH counts rows matching LIKE 'profile_enrich%.end', so a
    nested step under that name would emit a second countable row and make every
    autofill spend two of the user's twenty.
    """
    if not gathered:
        return {}
    prompt = "\n\n".join(f"## {k}\n{v}" for k, v in gathered.items() if v)
    if not prompt.strip():
        return {}
    with trace.step(session_id, "enrich.propose", model=DEFAULTS["ingest"]) as ctx:
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
        ctx["finish_reason"] = completion.choices[0].finish_reason
        if completion.usage:
            ctx["tokens_in"] = completion.usage.prompt_tokens
            ctx["tokens_out"] = completion.usage.completion_tokens
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
            fetched = (
                _github_material(url)
                if label == "github"
                else _nimble_material(label, url, session_id)
            )
            gathered[label] = fetched.text
            statuses.append(SourceStatus(label, fetched.ok, fetched.detail))
        proposed = _propose(gathered, session_id)
        ctx["sources_ok"] = sum(1 for s in statuses if s.ok)
        ctx["fields_proposed"] = len(proposed)

    return AutofillResult(proposed=proposed, sources=statuses)
