"""Server-side quotas for the surfaces Merit pays for.

Track and the help assistant run on Merit's API key, so they need a bound.
The bound is enforced here and not in the Next.js client, because the
backend connects to Supabase as service role and bypasses RLS -- anything
enforced only in the UI is enforced nowhere.

Quotas fail OPEN: if the ledger cannot be read, a user is not locked out of
their own evidence. The ledger is a cost-control mechanism, not a security
boundary, and the failure mode of over-serving is much cheaper than the
failure mode of a user unable to reach their own petition data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from paperpilot.supabase_client import user_event_count

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Quota:
    """A limit on how many of one kind of paid-for operation a user may run."""

    kind_prefix: str
    limit: int
    window_days: int
    noun: str


DOSSIER = Quota(kind_prefix="evidence_dossier", limit=3, window_days=30, noun="dossier export")
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
    from paperpilot import trace

    if byok_in_effect():
        return
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
    except Exception:  # noqa: BLE001 -- fail open, see module docstring
        logger.exception("quota check failed for user=%s quota=%s", user_id, quota.noun)
        return

    if used < quota.limit:
        return

    period = "day" if quota.window_days == 1 else "month"
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"You have used all {quota.limit} {quota.noun}s for this {period} "
            f"({quota.limit} per {period}). This surface runs on Merit's API key, "
            "which is why it is capped."
        ),
    )
