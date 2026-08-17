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

# Addresses that match _EMAIL_RE on a scraped page but are never a human to
# write to: bounce mailboxes, doc placeholders, tracking hosts, and the
# `sprite@2x.png` style filenames that a naive email regex happily accepts.
_JUNK_EMAIL_RE = re.compile(
    r"(^|@)(no-?reply|donotreply|postmaster|mailer-daemon)"
    r"|@(example|test|localhost|sentry\.io|wixpress\.com|domain\.com)"
    r"|\.(png|jpe?g|gif|webp|svg|css|js|woff2?)$"
    r"|@\d+\.\d+",
    re.I,
)

# Local parts that are a desk rather than a person. Still offered, but ranked
# below a named address so "Select" prefers a human where one exists.
_ROLE_LOCALPARTS = frozenset(
    {
        "info", "contact", "admin", "support", "hello", "office", "help",
        "enquiries", "enquiry", "inquiries", "editor", "editorial", "press",
        "media", "sales", "team", "mail", "webmaster", "journals", "library",
        "permissions", "privacy", "legal", "security", "abuse", "careers",
        "jobs", "hr", "marketing", "billing", "orders", "service", "services",
    }
)

# Common on-page obfuscation, unwrapped before the email regex runs.
_DEOBFUSCATE = (
    ("&#64;", "@"), ("&commat;", "@"), ("%40", "@"),
    ("[at]", "@"), ("(at)", "@"), ("{at}", "@"),
    ("[dot]", "."), ("(dot)", "."), ("{dot}", "."),
)

# Words that sit next to the address a paper actually wants you to write to.
_CORRESPONDING_RE = re.compile(
    r"correspond|corresponding author|reprint|contact author|for inquiries",
    re.I,
)

# Keys a page-extract payload may carry an author name under.
_AUTHOR_KEYS = ("author", "authors", "byline", "creator", "publisher_name")

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
    # "contact email" biases the result set toward pages that actually carry a
    # reachable address (faculty pages, lab sites, corresponding-author blocks)
    # instead of bare article landing pages.
    query = f"{qualifier} {context} contact email".strip()
    session_id = trace.new_session(user_id)
    hits = nimble_client.search(query, session_id, k=limit) or []
    people: list[dict[str, str]] = []
    for hit in hits:
        emails = _usable_emails(hit.snippet or "")
        people.append(
            {
                # `title` is the page, `name` is a human. A search hit gives us
                # the former and almost never the latter, so name stays empty
                # unless resolve_contact finds a real one -- writing a page
                # title into the recipient field is what this separation fixes.
                "name": "",
                "title": hit.title,
                "detail": hit.snippet,
                "url": hit.url,
                "email": emails[0] if emails else "",
            }
        )
    return {"configured": True, "people": people, "reason": ""}


def _usable_emails(text: str) -> list[str]:
    """Pull plausible human-reachable emails out of page or snippet text.

    De-obfuscates the common `name [at] domain` and HTML-entity forms first,
    drops bounce mailboxes, doc placeholders, and image filenames that the
    loose email regex otherwise accepts, then de-duplicates case-insensitively
    while preserving page order.
    """
    lowered = text
    for needle, repl in _DEOBFUSCATE:
        lowered = lowered.replace(needle, repl)
    seen: set[str] = set()
    out: list[str] = []
    for raw in _EMAIL_RE.findall(lowered):
        addr = raw.strip(".,;:'\"()<>[]").lower()
        if _JUNK_EMAIL_RE.search(addr) or addr in seen or len(addr) > 254:
            continue
        seen.add(addr)
        out.append(addr)
    return out


def _rank_emails(emails: list[str], text: str) -> list[str]:
    """Order candidate addresses best-first for a one-click Select.

    A corresponding-author address wins, then any address whose local part
    looks like a person, then role desks like info@ or editorial@.
    """

    def score(addr: str) -> tuple[int, int]:
        local = addr.split("@", 1)[0]
        near = 0
        idx = text.lower().find(addr)
        if idx != -1 and _CORRESPONDING_RE.search(text[max(0, idx - 300) : idx]):
            near = -2
        role = 1 if local.split("+")[0] in _ROLE_LOCALPARTS else 0
        return (near + role, emails.index(addr))

    return sorted(emails, key=score)


def _name_from_payload(payload: Any) -> str:
    """Best-effort author name from an extract payload's metadata keys."""
    data = payload.get("data") if isinstance(payload, dict) else None
    for source in (data, payload):
        if not isinstance(source, dict):
            continue
        for key in _AUTHOR_KEYS:
            value = source.get(key)
            if isinstance(value, list) and value:
                value = value[0]
            if isinstance(value, str) and 2 < len(value.strip()) <= 80:
                return value.strip()
    return ""


def _name_from_email(addr: str) -> str:
    """Derive a display name from an address local part, or "" if it is a desk.

    `j.smith@ox.ac.uk` becomes "J Smith". Role mailboxes and opaque local
    parts return "" rather than a guess -- an empty name field is honest, a
    wrong one gets written into a real email.
    """
    local = addr.split("@", 1)[0]
    if local in _ROLE_LOCALPARTS or any(c.isdigit() for c in local):
        return ""
    parts = [p for p in re.split(r"[._\-+]+", local) if p.isalpha()]
    if len(parts) < 2:
        return ""
    return " ".join(p.capitalize() for p in parts)


def resolve_contact(user_id: str, url: str) -> dict[str, Any]:
    """Open one lead's page and pull a real contact address out of it.

    Web search returns pages, not people, so the address a user needs lives in
    the page body (a corresponding-author block, a faculty contact line) and
    never in the search snippet. This fetches the page through Nimble Extract
    on demand -- one lead, only when the user picks it -- and returns
    {found, email, emails, name, reason}. `reason` is always user-facing text
    when found is False, so the UI can say what to do next instead of showing
    an empty field.
    """
    empty = {"found": False, "email": "", "emails": [], "name": "", "reason": ""}
    if not url.startswith(("http://", "https://")):
        return {**empty, "reason": "That lead has no page to open."}
    if not nimble_client.is_configured():
        return {
            **empty,
            "reason": (
                "Contact discovery is not configured. Open the page and copy "
                "the address in yourself."
            ),
        }
    session_id = trace.new_session(user_id)
    payload = nimble_client.extract(url, session_id)
    if not payload:
        return {
            **empty,
            "reason": (
                "Could not open that page. Open it yourself and copy the "
                "author's address in."
            ),
        }
    text = payload if isinstance(payload, str) else json.dumps(payload)
    emails = _rank_emails(_usable_emails(text), text)
    if not emails:
        return {
            **empty,
            "reason": (
                "No public email address on that page. Open it and copy the "
                "author's address in, or type a recipient yourself."
            ),
        }
    best = emails[0]
    return {
        "found": True,
        "email": best,
        "emails": emails[:8],
        "name": _name_from_payload(payload) or _name_from_email(best),
        "reason": "",
    }


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
