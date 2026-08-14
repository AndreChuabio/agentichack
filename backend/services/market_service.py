"""Market service: user profile + outreach drafting over Supabase.

Ports the profile and outreach_log persistence from the legacy ClickHouse
helpers in paperpilot.outreach.log to Supabase Postgres, and wraps the
existing outreach orchestrator so generation logic is reused unchanged. Only
the data layer moves; LLM/Senso logic stays in paperpilot.outreach.*.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from paperpilot import nimble_client, supabase_client, trace
from paperpilot.outreach.orchestrator import generate_drafts
from paperpilot.outreach.purpose import Purpose
from paperpilot.outreach.senso import Senso

# Loose email matcher for pulling a contact out of a web-search snippet.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Per-purpose phrasing that turns the user's context into a people-finding query.
_PEOPLE_QUERY: dict[str, str] = {
    "VISA": "experts, reference-letter writers, and program organizers in",
    "CAREER": "hiring managers, recruiters, and engineering leads working on",
    "NETWORK": "researchers and practitioners working on",
    "BRAND": "creators, podcast hosts, and community leaders covering",
    "SERVICE": "founders and teams who might need help with",
}

# Profile columns in upsert order. updated_at is set by the writer.
_PROFILE_FIELDS = [
    "name", "title", "about", "voice_tone",
    "github_url", "linkedin_url", "scholar_url", "site_url", "resume_text",
    "selected_repos",
]

# Profile columns stored as jsonb rather than text, so they are serialised on
# write and arrive already parsed on read.
_JSON_FIELDS = frozenset({"selected_repos"})


@dataclass
class Profile:
    """A user's outreach profile. Empty strings are the schema defaults."""

    user_id: str
    name: str = ""
    title: str = ""
    about: str = ""
    voice_tone: str = ""
    github_url: str = ""
    linkedin_url: str = ""
    scholar_url: str = ""
    site_url: str = ""
    resume_text: str = ""
    selected_repos: list[str] = field(default_factory=list)


class _LogAdapter:
    """Adapter exposing log_generate so the orchestrator can record events.

    The orchestrator calls logger.log_generate(...); we forward to the
    Supabase writer. Holding the user_id and a shared connection keeps each
    insert cheap and correctly scoped.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def log_generate(
        self,
        user_id: str,
        purpose: str,
        channel: str,
        content_type_id: str,
        sample_job_id: str,
    ) -> str:
        """Insert one generate-event row; return the sample_job_id."""
        insert_outreach_log(
            user_id=user_id,
            purpose=purpose,
            channel=channel,
            content_type_id=content_type_id,
            sample_job_id=sample_job_id,
            conn=self._conn,
        )
        return sample_job_id


def get_profile(user_id: str, conn: Any | None = None) -> Profile:
    """Return the user's profile, or empty defaults if none exists."""
    own_conn = conn is None
    conn = conn or supabase_client.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, title, about, voice_tone, github_url, "
                "linkedin_url, scholar_url, site_url, resume_text, "
                "selected_repos "
                "FROM user_profile WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
    finally:
        if own_conn:
            conn.close()
    if row is None:
        return Profile(user_id=user_id)
    values = dict(zip(_PROFILE_FIELDS, row))
    # selected_repos arrives already parsed from a jsonb column. A hand-edited
    # row could hold any JSON, so anything that is not a list of strings is
    # read as no selection rather than being handed to the form as-is.
    repos = values.get("selected_repos")
    values["selected_repos"] = (
        [str(item) for item in repos] if isinstance(repos, list) else []
    )
    return Profile(user_id=user_id, **values)


def _serialise(name: str, value: Any) -> str:
    """One profile value in the form its column takes.

    A jsonb column will not accept str(["a"]): Python's repr quotes with
    apostrophes and is not JSON, so list fields are dumped rather than
    stringified. Everything else is plain text.
    """
    if name in _JSON_FIELDS:
        items = value if isinstance(value, (list, tuple)) else []
        return json.dumps([str(item) for item in items])
    return str(value)


def upsert_profile(
    user_id: str, fields: dict[str, Any], conn: Any | None = None
) -> Profile:
    """Upsert the caller's profile row keyed on user_id.

    Only known profile fields are written; unknown keys are ignored. Missing
    fields fall back to the schema default (empty string, or an empty array for
    the jsonb columns) on insert and are left unchanged on update.
    """
    own_conn = conn is None
    conn = conn or supabase_client.get_conn()
    clean = {
        k: _serialise(k, fields[k])
        for k in _PROFILE_FIELDS
        if fields.get(k) is not None
    }
    cols = ["user_id", *clean.keys(), "updated_at"]
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join(
        f"{col} = excluded.{col}" for col in (*clean.keys(), "updated_at")
    )
    values: list[Any] = [user_id, *clean.values(), datetime.now()]
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO user_profile ({', '.join(cols)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (user_id) DO UPDATE SET {updates}",
                values,
            )
    finally:
        if own_conn:
            conn.close()
    return get_profile(user_id)


def insert_outreach_log(
    user_id: str,
    purpose: str,
    channel: str,
    content_type_id: str,
    sample_job_id: str,
    draft_id: str = "",
    posted: bool = False,
    recipient_name: str = "",
    recipient_contact: str = "",
    conn: Any | None = None,
) -> None:
    """Insert one outreach_log row scoped to user_id."""
    own_conn = conn is None
    conn = conn or supabase_client.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO outreach_log "
                "(user_id, purpose, channel, content_type_id, "
                "sample_job_id, draft_id, posted, "
                "recipient_name, recipient_contact) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    user_id, purpose, channel, content_type_id,
                    sample_job_id, draft_id, posted,
                    recipient_name, recipient_contact,
                ),
            )
    finally:
        if own_conn:
            conn.close()


def log_sent(
    user_id: str,
    purpose: str,
    channel: str,
    recipient_name: str,
    recipient_contact: str,
    draft_id: str = "",
    conn: Any | None = None,
) -> None:
    """Record that the caller sent a draft to a named recipient (posted=True)."""
    insert_outreach_log(
        user_id=user_id,
        purpose=purpose,
        channel=channel,
        content_type_id="",
        sample_job_id="",
        draft_id=draft_id,
        posted=True,
        recipient_name=recipient_name,
        recipient_contact=recipient_contact,
        conn=conn,
    )


def suggest_people(
    user_id: str, purpose: str, context: str, limit: int = 6
) -> dict[str, Any]:
    """Suggest people/orgs to reach via Nimble web search.

    Returns {"configured": bool, "people": [...], "reason": str}. Nimble is an
    optional accelerant, not a precondition: when it is unconfigured this
    returns configured=False with an empty list and a "reason" explaining
    that contact discovery is optional so the UI can present it as such
    rather than as a broken feature. Emails are best-effort extracted from
    result snippets; many results will have none.
    """
    if not nimble_client.is_configured():
        return {
            "configured": False,
            "people": [],
            "reason": (
                "Contact discovery is an optional integration and is not "
                "configured. Enter the recipient's name and contact yourself "
                "to continue -- drafting works without it."
            ),
        }
    qualifier = _PEOPLE_QUERY.get(
        purpose.upper(), "people and organizations working on"
    )
    query = f"{qualifier} {context}".strip()
    session_id = trace.new_session(user_id)
    hits = nimble_client.search(query, session_id, k=limit) or []
    people: list[dict[str, str]] = []
    for hit in hits:
        emails = _EMAIL_RE.findall(hit.snippet or "")
        people.append(
            {
                "name": hit.title,
                "detail": hit.snippet,
                "url": hit.url,
                "email": emails[0] if emails else "",
            }
        )
    return {"configured": True, "people": people, "reason": ""}


def list_outreach_log(
    user_id: str, limit: int = 50, conn: Any | None = None
) -> list[dict[str, Any]]:
    """Return the user's most recent outreach_log rows, newest first."""
    own_conn = conn is None
    conn = conn or supabase_client.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ts, purpose, channel, content_type_id, "
                "sample_job_id, draft_id, posted, "
                "recipient_name, recipient_contact FROM outreach_log "
                "WHERE user_id = %s ORDER BY ts DESC LIMIT %s",
                (user_id, limit),
            )
            rows = cur.fetchall()
    finally:
        if own_conn:
            conn.close()
    return [
        {
            "id": r[0],
            "ts": r[1].isoformat() if r[1] is not None else None,
            "purpose": r[2],
            "channel": r[3],
            "content_type_id": r[4],
            "sample_job_id": r[5],
            "draft_id": r[6],
            "posted": r[7],
            "recipient_name": r[8],
            "recipient_contact": r[9],
        }
        for r in rows
    ]


def generate_outreach(
    user_id: str,
    purpose: str,
    context: str,
    sender_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate outreach draft cards for a purpose and log each event.

    Reuses paperpilot.outreach.orchestrator.generate_drafts for all LLM and
    Senso work; this layer only supplies a Supabase-backed logger and opens a
    session. Senso is optional: when configured it is used for its brand-kit
    tone retrieval, otherwise drafting runs on a direct LLM call.

    `sender_profile` is the caller's saved user_profile as a dict and is the
    sender identity every draft is written as. When the router does not
    supply one it is loaded here from user_id, so no caller of this function
    can generate drafts detached from the caller's own identity.
    """
    try:
        purpose_enum = Purpose(purpose)
    except ValueError as exc:
        raise ValueError(f"Unknown purpose: {purpose!r}") from exc

    # Senso is an optional enhancement, not a precondition. Without a key we
    # draft with a direct LLM call on the caller's own key, which is the path
    # every self-hosted user takes.
    senso = Senso.from_env() if os.environ.get("SENSO_API_KEY") else None

    if sender_profile is None:
        profile = get_profile(user_id)
        sender_profile = {
            k: v for k, v in asdict(profile).items() if k != "user_id"
        }

    session_id = trace.new_session(user_id)
    conn = supabase_client.get_conn()
    try:
        logger = _LogAdapter(conn)
        cards = generate_drafts(
            senso=senso,
            purpose=purpose_enum,
            context=context,
            session_id=session_id,
            user_id=user_id,
            logger=logger,
            sender_profile=sender_profile,
        )
    finally:
        conn.close()
    return [asdict(card) for card in cards]
