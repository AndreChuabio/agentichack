"""Outreach orchestrator: purpose -> draft cards.

Wraps every generation call in `paperpilot.trace.step` so the existing Lapdog
pipeline captures each step into Datadog. Errors on one channel do not
cancel the others — the failing card carries an `error` string for the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from paperpilot import trace
from paperpilot.outreach import llm_draft
from paperpilot.outreach.content_types import CONTENT_TYPE_CONFIGS
from paperpilot.outreach.purpose import Purpose, channels_for
from paperpilot.outreach.senso import Senso


@dataclass
class DraftCard:
    channel: str
    content_type_id: str
    sample_job_id: str
    markdown: str
    draft_id: str = ""
    error: str | None = None


def _build_context(purpose: Purpose, user_context: str) -> str:
    purpose_blurbs = {
        Purpose.VISA: (
            "Audience: conference organizers, journal editors, and selection "
            "committees evaluating extraordinary-ability candidates."
        ),
        Purpose.CAREER: (
            "Audience: a peer or senior whose work overlaps yours, "
            "approached for networking or mentorship."
        ),
        Purpose.NETWORK: (
            "Audience: a research lab, faculty member, or principal "
            "investigator. Tone: academic-warm. Goal: open a conversation "
            "about visiting/collaborating on shared research interests."
        ),
        Purpose.BRAND: (
            "Audience: your professional network. Build credibility around "
            "the topic below; do not pitch a product."
        ),
        Purpose.SERVICE: (
            "Audience: prospective clients who might pay for the service/"
            "product described below. Value-first; one CTA."
        ),
    }
    return f"{purpose_blurbs[purpose]}\n\nContext from the author:\n{user_context}"


def generate_drafts(
    senso: Senso | None,
    purpose: Purpose | str,
    context: str,
    session_id: str,
    user_id: str,
    logger: Any | None = None,
    sender_profile: dict[str, Any] | None = None,
) -> list[DraftCard]:
    """Generate one draft card per channel mapped to `purpose`.

    `sender_profile` is the authed caller's saved user_profile (name, title,
    links, resume text, ...) and is the only permitted source of the sender's
    identity in every draft. An empty profile yields neutral placeholders,
    never an identity taken from retrieved content.

    `senso` is optional. When absent, drafting happens with a direct LLM call
    on the caller's own key, which is the path every open-source user takes.
    When present, Senso is used for its brand-kit tone retrieval only: its
    generated sample is passed to the LLM as a quarantined style reference,
    and the final draft is always written by the LLM as the caller. Senso
    output used to be returned verbatim as the draft, which let a workspace
    knowledge base containing one user's resume write every other user's
    drafts as that person -- a cross-user PII leak.

    `user_id` is the authed caller; required so outreach_log rows are scoped to
    the right user. `logger` is an `outreach.log` module reference or any object
    exposing `log_generate(...)`. Passing it explicitly keeps the function
    testable.
    """
    if isinstance(purpose, str):
        purpose = Purpose(purpose)

    full_context = _build_context(purpose, context)
    cards: list[DraftCard] = []

    for channel in channels_for(purpose):
        ct_config = CONTENT_TYPE_CONFIGS.get(channel, {"template": ""})
        backend_name = "senso_tone+llm.generate" if senso else "llm.generate"
        with trace.step(
            session_id,
            backend_name,
            purpose=purpose.value,
            channel=channel,
        ) as ctx:
            try:
                if senso is not None:
                    ct_id = senso.get_or_create_content_type(channel, ct_config)
                    ctx["content_type_id"] = ct_id
                    job_id = senso.generate_sample(ct_id, full_context)
                    ctx["job_id"] = job_id
                    job = senso.poll_until_done(job_id, timeout_s=30.0, interval_s=1.0)
                    # Senso's sample is tone/style material only. It is never
                    # returned as the draft: the workspace knowledge base can
                    # contain another person's resume, so treating its output
                    # as the message would leak that identity to the caller.
                    style_reference = job.get("result", {}).get("raw_markdown", "")
                    draft_id = job.get("result", {}).get("content_id", "")
                else:
                    ct_id = ""
                    job_id = ""
                    draft_id = ""
                    style_reference = ""
                md = llm_draft.draft_channel(
                    channel,
                    full_context,
                    sender_profile=sender_profile,
                    style_reference=style_reference,
                )

                ctx["draft_chars"] = len(md)
                if logger is not None:
                    logger.log_generate(
                        user_id=user_id,
                        purpose=purpose.value,
                        channel=channel,
                        content_type_id=ct_id,
                        sample_job_id=job_id,
                    )
                cards.append(DraftCard(
                    channel=channel,
                    content_type_id=ct_id,
                    sample_job_id=job_id,
                    markdown=md,
                    draft_id=draft_id,
                ))
            except Exception as exc:  # noqa: BLE001 -- one channel failing must not cancel the rest
                ctx["error"] = str(exc)
                cards.append(DraftCard(
                    channel=channel,
                    content_type_id="",
                    sample_job_id="",
                    markdown="",
                    error=str(exc),
                ))
    return cards
