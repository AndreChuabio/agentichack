"""Server-side quotas for the surfaces Merit pays for.

Track and the help assistant run on Merit's API key, so they need a bound.
The bound is enforced here and not in the Next.js client, because the
backend connects to Supabase as service role and bypasses RLS -- anything
enforced only in the UI is enforced nowhere.

Quotas fail CLOSED with a retryable 503: every quota here guards a surface
where Merit is spending real money per request, and the moment the ledger
becomes unreadable is exactly the moment of peak load, when an open gate
turns a traffic spike into an unbounded bill. Reading a user's own stored
evidence is never quota-gated, so failing closed here blocks only new
generation, not access to petition data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from paperpilot.supabase_client import user_event_count

logger = logging.getLogger(__name__)


_MERIT_KEY_REASON = (
    "This surface runs on Merit's API key, which is why it is capped."
)
_ABUSE_CEILING_REASON = (
    "This ceiling exists to catch runaway automation, not to limit what you "
    "bought. Contact support if you genuinely need more."
)


@dataclass(frozen=True)
class Quota:
    """A limit on how many of one kind of paid-for operation a user may run."""

    kind_prefix: str
    limit: int
    window_days: int
    noun: str
    # Why this cap exists, shown to the user in the 429. Defaults to the
    # cost-control wording, which is true of every cap except the ones that
    # apply to a customer who has already paid.
    reason: str = _MERIT_KEY_REASON


DOSSIER = Quota(kind_prefix="evidence_dossier", limit=3, window_days=30, noun="dossier export")
# The cap a paying customer gets instead of DOSSIER. Regenerating the dossier
# after editing evidence is the normal way the product is used, so charging $99
# and then refusing the fourth export is the wrong failure. Same kind_prefix, so
# it counts the same emitted evidence_dossier.end rows.
DOSSIER_PAID = Quota(
    kind_prefix="evidence_dossier",
    limit=30,
    window_days=30,
    noun="dossier export",
    reason=_ABUSE_CEILING_REASON,
)
NARRATIVE = Quota(kind_prefix="evidence_draft", limit=30, window_days=30, noun="criterion narrative")
ASSIST = Quota(kind_prefix="assist", limit=20, window_days=1, noun="assistant question")
SITE = Quota(kind_prefix="site_build", limit=5, window_days=30, noun="portfolio site build")
ENRICH = Quota(kind_prefix="profile_enrich", limit=20, window_days=30, noun="profile autofill")

# Caps that apply only to callers running on Merit's key. Each of these is
# output-bounded at a few hundred tokens, which is why Merit absorbs them at
# all; the repo-reading surfaces stay on the caller's own key because a 600K
# token bundle has no comparable ceiling.
# The prefixes are deliberately their own namespace rather than reusing the
# kinds these paths already emit. draft.py emits one "draft.<section>" event per
# section and cfp_match emits both "match.embed" and "match.nimble_augment", so
# a prefix of "draft" or "match" would count several rows for a single request
# and burn the cap at an unpredictable rate. These match exactly one row each.
DRAFT = Quota(kind_prefix="quota_draft", limit=10, window_days=30, noun="paper draft")
MATCH = Quota(kind_prefix="quota_match", limit=40, window_days=30, noun="venue match")
OUTREACH = Quota(
    kind_prefix="quota_outreach", limit=20, window_days=30, noun="outreach draft"
)
# Repo ingest on the first-party Vertex path runs on Merit's GCP project no
# matter what X-LLM-Key the caller sent, and a single confirmed-large run can
# reach 600K input tokens. Enforced via admit_always because the BYOK
# exemption does not apply where the platform pays anyway.
INGEST = Quota(kind_prefix="quota_ingest", limit=10, window_days=30, noun="repo ingest")


def admit(user_id: str, quota: Quota) -> None:
    """Check a cap and record the request against it, unless the caller is BYOK.

    Somebody who supplied an X-LLM-Key is paying for their own inference, so
    capping them would charge them for the privilege of not costing us anything.
    The cap bounds Merit's spend and applies exactly where Merit is spending.

    The request is counted on admission rather than on success. That charges a
    failed call, which is the conservative direction: the alternative leaves a
    surface where anything that reliably errors late is free to retry forever.
    """
    from backend.byok import byok_in_effect

    if byok_in_effect():
        return
    admit_always(user_id, quota)


def admit_always(user_id: str, quota: Quota) -> None:
    """Check a cap and record the request, with no BYOK exemption.

    For surfaces where Merit pays regardless of the caller's key -- the
    first-party Vertex ingest path authenticates with Merit's service account
    and never spends the X-LLM-Key the endpoint required.
    """
    from paperpilot import trace

    enforce(user_id, quota)
    # Emit the single row this quota counts. Bound to the caller, because a
    # NULL-user row is invisible to user_event_count's WHERE user_id filter.
    session_id = trace.new_session(user_id)
    with trace.step(session_id, quota.kind_prefix, user_id=user_id):
        pass


def enforce(user_id: str, quota: Quota) -> None:
    """Raise 429 when the user is at or over the limit for this quota."""
    since = datetime.now(timezone.utc) - timedelta(days=quota.window_days)
    try:
        used = user_event_count(user_id, quota.kind_prefix, since)
    except Exception as exc:  # noqa: BLE001 -- fail closed, see module docstring
        logger.exception("quota check failed for user=%s quota=%s", user_id, quota.noun)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Merit is unusually busy right now and could not verify your "
                "usage. Please try again in a moment."
            ),
        ) from exc

    if used < quota.limit:
        return

    period = "day" if quota.window_days == 1 else "month"
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"You have used all {quota.limit} {quota.noun}s for this {period} "
            f"({quota.limit} per {period}). {quota.reason}"
        ),
    )
