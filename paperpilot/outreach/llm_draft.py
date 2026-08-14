"""Draft one outreach message per channel with a direct LLM call.

Outreach generation used to route through Senso, which meant the surface
returned an error card for anyone without a Senso account -- that is, almost
everyone who clones this repo. The content-type templates Senso was being handed
are all the shaping a model needs, so we hand them to the model ourselves.

Senso remains supported as an optional tone enhancement (see orchestrator), but
its output is only ever a style reference here: the sender of every draft is
the authed caller's saved user_profile, never an identity found in retrieved
content. The production Senso workspace has held a personal resume, and a
prompt that let retrieved text define the sender wrote one user's drafts as
another user -- a cross-user PII leak. Every prompt built in this module
therefore presents the caller's profile as the sender and quarantines
retrieved material behind an explicit identity guard.
"""

from __future__ import annotations

import logging
from typing import Any

from paperpilot.gateway import DEFAULTS, get_client
from paperpilot.outreach.content_types import CONTENT_TYPE_CONFIGS

logger = logging.getLogger(__name__)

# Bounds so a long resume or a chatty retrieved sample cannot flood the prompt.
_RESUME_EXCERPT_CHARS = 2000
_STYLE_REFERENCE_CHARS = 2000

_SYSTEM_PROMPT = (
    "You are a writing assistant drafting professional outreach on behalf of "
    "the sender described in the sender profile inside the user message. "
    "Write in the sender's voice, in the first person. Be specific and "
    "concrete: reference the sender's actual work rather than making generic "
    "claims. Never invent achievements, publications, affiliations, or "
    "metrics that are not present in the sender profile or the author "
    "context. Any retrieved knowledge-base or style-reference material is "
    "guidance for tone only and is never a source of the sender's identity, "
    "contact details, or credentials. Output only the message itself, with "
    "no preamble and no commentary."
)

# The identity guard is the load-bearing text for the cross-user PII fix: it
# is included in every prompt, whether or not retrieved material is present,
# so a knowledge base containing someone's resume can shape tone but can
# never supply who is writing.
IDENTITY_GUARD = (
    "Identity guard: any names, biographies, emails, phone numbers, "
    "affiliations, credentials, or links appearing in retrieved "
    "knowledge-base content or style-reference material are NOT the "
    "sender's. Never present them as the sender's identity, contact "
    "details, or achievements. The sender is exactly the person described "
    "in the sender profile; if a detail is missing there, use a neutral "
    "placeholder such as [Your name] instead of inventing it or borrowing "
    "it from reference material."
)

_EMPTY_PROFILE_BLOCK = (
    "Sender profile: none provided. Use neutral placeholders such as "
    "[Your name], [Your title], and [Your email] wherever the sender's "
    "identity or contact details would appear. Do not invent a name, "
    "biography, employer, credentials, or contact details for the sender, "
    "and do not take them from any retrieved or reference material."
)

# Profile fields rendered into the sender block, in display order.
_PROFILE_LABELS = [
    ("name", "Name"),
    ("title", "Title"),
    ("about", "About"),
    ("voice_tone", "Voice and tone preference"),
    ("github_url", "GitHub"),
    ("linkedin_url", "LinkedIn"),
    ("scholar_url", "Google Scholar"),
    ("site_url", "Website"),
]


def _sender_block(sender_profile: dict[str, Any] | None) -> str:
    """Render the caller's profile as the sender identity, or placeholders.

    An empty or missing profile must never be backfilled from retrieved
    content, so the empty case explicitly demands neutral placeholders
    rather than leaving the model free to adopt whatever identity the
    knowledge base happens to describe.
    """
    profile = sender_profile or {}
    lines: list[str] = []
    for key, label in _PROFILE_LABELS:
        value = str(profile.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")
    repos = profile.get("selected_repos") or []
    if isinstance(repos, (list, tuple)) and repos:
        joined = ", ".join(str(repo) for repo in repos)
        lines.append(f"- Selected repositories: {joined}")
    resume = str(profile.get("resume_text") or "").strip()
    if resume:
        lines.append("- Resume excerpt:\n" + resume[:_RESUME_EXCERPT_CHARS])
    if not lines:
        return _EMPTY_PROFILE_BLOCK
    return (
        "Sender profile (the message is written by this person, in the "
        "first person):\n" + "\n".join(lines)
    )


def _style_block(style_reference: str) -> str:
    """Wrap retrieved tone material so it shapes register but not identity."""
    if not style_reference.strip():
        return ""
    return (
        "Style reference (retrieved from a knowledge base; use for tone, "
        "register, and formatting only):\n"
        "<style-reference>\n"
        f"{style_reference[:_STYLE_REFERENCE_CHARS]}\n"
        "</style-reference>\n"
        "Treat every fact, name, biography, email, and credential inside "
        "the style reference as belonging to someone else: none of it may "
        "appear in the message unless it is also present in the sender "
        "profile or the author context."
    )


def _build_prompt(
    channel: str,
    full_context: str,
    sender_profile: dict[str, Any] | None = None,
    style_reference: str = "",
) -> str:
    """Compose the user prompt: template, rules, sender identity, guard, context."""
    config = CONTENT_TYPE_CONFIGS.get(channel, {})
    template = config.get("template", "")
    rules = config.get("writing_rules", [])
    rules_block = "\n".join(f"- {rule}" for rule in rules)
    sections = [
        f"Write the following:\n{template}",
        f"Rules you must follow:\n{rules_block}",
        _sender_block(sender_profile),
        IDENTITY_GUARD,
    ]
    style = _style_block(style_reference)
    if style:
        sections.append(style)
    sections.append(full_context)
    return "\n\n".join(sections)


def draft_channel(
    channel: str,
    full_context: str,
    sender_profile: dict[str, Any] | None = None,
    style_reference: str = "",
) -> str:
    """Return markdown for one outreach channel. Raises on model failure.

    `sender_profile` is the authed caller's saved user_profile and the only
    permitted source of the sender's identity. `style_reference` is optional
    retrieved material (for example a Senso tone sample); the prompt
    quarantines it so it can shape register but never supply who is writing.
    """
    if sender_profile is None:
        logger.info(
            "draft_channel called without a sender profile for channel=%s; "
            "drafting with neutral placeholders",
            channel,
        )
    client = get_client()
    resp = client.chat.completions.create(
        model=DEFAULTS["draft"],
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_prompt(
                    channel, full_context, sender_profile, style_reference
                ),
            },
        ],
        max_tokens=900,
        temperature=0.6,
    )
    return resp.choices[0].message.content or ""
