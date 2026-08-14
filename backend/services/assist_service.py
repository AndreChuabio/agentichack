"""Assist service: stream an O-1A coaching answer, Vertex-first.

Backs the global "Help me" assistant. Given a plain-English question, the
surface the user is on (track / productize / market), and an optional context
dict (current path, counts, etc.), this streams a coaching answer token by
token.

The help assistant runs on Merit's own key (backend/quotas.py), which makes
it a Merit-dime surface: when paperpilot.vertex.vertex_enabled() is true it
streams first-party Gemini on Vertex AI; otherwise it falls back to Claude
through the Vercel AI Gateway, unchanged from before Vertex support existed.
Either path records token usage against surface="assist".

The system prompt teaches the model what Merit is, the three surfaces, the
eight O-1A criteria in plain English, and the key rule that only three of the
eight criteria are needed (not all eight). The coach maps Productize outputs
to O-1A criteria: a generated paper supports "Published / scholarly articles",
and a Claude plugin supports "Original contributions of major significance".
Answers coach next steps and concrete evidence, contain no emojis, and are not
legal advice.
"""

from __future__ import annotations

import json
from typing import Any, Generator

from paperpilot import trace, vertex
from paperpilot.gateway import DEFAULTS, get_client
from paperpilot.outreach.evidence import USCIS_O1A_CRITERIA

# Plain-English label per criterion key, sourced from the canonical USCIS set
# so the coach and the Track ledger never drift. Rendered into the system
# prompt as a numbered list the model can reference by name.
CRITERIA_GUIDE: list[tuple[str, str]] = list(USCIS_O1A_CRITERIA)

_VALID_SURFACES: set[str] = {"track", "productize", "market", "publish", "cfp"}


def _criteria_block() -> str:
    """Render the eight O-1A criteria as a numbered plain-English list."""
    lines = [
        f"{idx}. {label}"
        for idx, (_key, label) in enumerate(CRITERIA_GUIDE, start=1)
    ]
    return "\n".join(lines)


SYS = (
    "You are the Merit assistant, an encouraging coach who helps people build "
    "a United States O-1A extraordinary-ability visa case. Speak to a smart "
    "non-expert who does not know the O-1A criteria. Be warm, concrete, and "
    "brief. Use short paragraphs or simple lists.\n\n"
    "Merit has five surfaces:\n"
    "- Track: the main surface. An evidence ledger where the user records "
    "real accomplishments against the eight O-1A criteria and sees how many "
    "criteria they satisfy.\n"
    "- Productize: turns a code repository into a published paper and a "
    "Claude plugin, which become evidence the user can Track.\n"
    "- Market: the user's profile plus outreach drafts to reach people who "
    "can support the case (recommendation letters, judging invitations, "
    "media).\n"
    "- Publish: turns the user's repositories and profile into a hosted "
    "portfolio site with a public link that makes their work legible to "
    "reviewers and attorneys.\n"
    "- Call for Papers (cfp): a browsable list of venues and submission "
    "deadlines; publishing at one becomes evidence the user can Track.\n\n"
    "The eight O-1A criteria, in plain English:\n"
    f"{_criteria_block()}\n\n"
    "The single most important rule: USCIS requires evidence for at least "
    "THREE of these eight criteria, not all eight. Reassure users they do not "
    "need everything. Help them find the three (or more) where they are "
    "strongest.\n\n"
    "How Productize maps to evidence: a paper Merit drafts and publishes "
    "supports the 'Published material' and 'Authorship of scholarly articles' "
    "criteria; a Claude plugin built from their work supports 'Original "
    "scientific, scholarly, or business-related contributions of major "
    "significance'.\n\n"
    "When you answer: name the relevant criterion in plain English, suggest a "
    "concrete next step the user can take inside Merit, and give an example of "
    "evidence that would count. Never use emojis. Never use exclamation "
    "marks. You are not a lawyer and this is general guidance, not legal "
    "advice; say so briefly only if the user asks about eligibility or legal "
    "outcomes."
)


def _normalize_surface(surface: str) -> str:
    """Map an arbitrary surface string to a known surface, defaulting to track."""
    s = (surface or "").strip().lower()
    return s if s in _VALID_SURFACES else "track"


def _context_line(surface: str, context: dict[str, Any] | None) -> str:
    """Build the trailing line that grounds the answer in the user's place."""
    parts = [f"The user is currently on the {surface} surface."]
    if context:
        try:
            ctx_str = json.dumps(context, default=str, sort_keys=True)
        except (TypeError, ValueError):
            ctx_str = str(context)
        parts.append(f"Page context: {ctx_str}")
    parts.append(
        "Tailor the answer to this surface and context where it helps."
    )
    return " ".join(parts)


def assist_answer(
    question: str,
    surface: str,
    context: dict[str, Any] | None,
    session_id: str,
) -> Generator[str, None, None]:
    """Stream a coaching answer to the user's question as text deltas.

    Routes through Vertex AI when enabled, otherwise the Gateway (see module
    docstring). Either blocking stream is iterated synchronously; the router
    drives this generator off the event loop with iterate_in_threadpool and
    wraps each delta as an SSE message.
    """
    surface = _normalize_surface(surface)
    user_prompt = f"{question.strip()}\n\n{_context_line(surface, context)}"

    with trace.step(
        session_id,
        "assist",
        surface=surface,
    ) as ctx:
        chunks: list[str] = []
        if vertex.vertex_enabled():
            # Merit-dime surface: first-party Gemini on Vertex AI (a Google
            # Cloud product + the Gemini API), same pattern as repo ingest.
            model = DEFAULTS["assist_vertex"]
            ctx["provider"] = "vertex"
            ctx["model"] = model
            for delta in vertex.generate_text_stream(
                model,
                SYS,
                user_prompt,
                surface="assist",
                tenant_id=trace.session_user(session_id) or None,
                max_output_tokens=700,
                temperature=0.4,
            ):
                chunks.append(delta)
                yield delta
        else:
            model = DEFAULTS["draft"]
            ctx["provider"] = "gateway"
            ctx["model"] = model
            client = get_client()
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYS},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
                max_tokens=700,
                temperature=0.4,
            )
            for event in stream:
                delta = event.choices[0].delta.content if event.choices else None
                if delta:
                    chunks.append(delta)
                    yield delta
        ctx["chars"] = len("".join(chunks))
