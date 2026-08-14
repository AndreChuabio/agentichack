"""Vercel AI Gateway client.

Uses the OpenAI-compatible endpoint so we can route to Anthropic, Google, and
OpenAI providers from a single client. Provider/model is encoded in the model
string: e.g. "anthropic/claude-sonnet-4-6", "google/gemini-2.5-flash",
"openai/text-embedding-3-small".

Lapdog intercepts these calls when the process is wrapped via
`lapdog python ...` or `lapdog streamlit run ...`.
"""

from __future__ import annotations

import os
from contextvars import ContextVar

from openai import OpenAI


GATEWAY_BASE_URL = os.environ.get(
    "AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v1"
)

# The caller's own gateway key, bound per request by backend.byok. A ContextVar
# rather than a parameter because get_client() has nine call sites across the
# pipeline and the key must not be threaded through all of them. Starlette runs
# each request in its own task, so each request gets its own context copy and
# keys cannot leak between concurrent callers.
_REQUEST_KEY: ContextVar[str | None] = ContextVar("merit_request_llm_key", default=None)


def set_request_key(key: str | None) -> None:
    """Bind (or clear) the caller's gateway key for the current request context."""
    _REQUEST_KEY.set(key or None)


def current_request_key() -> str | None:
    """Return the gateway key bound to the current request context, if any.

    Read-only counterpart to set_request_key(). paperpilot.redaction imports
    this to redact the literal bound key from logs -- byok.require_llm_key
    accepts any non-empty string, not just the shapes redaction's regex
    patterns recognize, so the shape patterns alone cannot catch every key.
    This module must not import paperpilot.redaction (or anything else in
    paperpilot) to keep that import direction acyclic.
    """
    return _REQUEST_KEY.get()


def get_client() -> OpenAI:
    """Return an OpenAI client pointed at Vercel AI Gateway.

    Prefers the caller's own key when one is bound to this request (BYOK), and
    otherwise falls back to the server's key. Surfaces that run on Merit's dime
    (Track, the help assistant) bind nothing and get the server key; surfaces
    that run on the user's key (Productize, Market) bind theirs.
    """
    api_key = _REQUEST_KEY.get() or os.environ.get("AI_GATEWAY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No LLM API key available. Supply one via the X-LLM-Key header, or "
            "set AI_GATEWAY_API_KEY. Get a key at "
            "https://vercel.com/dashboard/ai-gateway"
        )
    # Bounded rather than the SDK's 600s default: a hung upstream call would
    # otherwise pin one of the limited worker threads for ten minutes.
    return OpenAI(
        base_url=GATEWAY_BASE_URL,
        api_key=api_key,
        timeout=180.0,
        max_retries=1,
    )


DEFAULTS = {
    "ingest": os.environ.get("MODEL_INGEST", "google/gemini-2.5-flash"),
    "draft": os.environ.get("MODEL_DRAFT", "anthropic/claude-sonnet-4-6"),
    "embed": os.environ.get("MODEL_EMBED", "openai/text-embedding-3-small"),
    # Used only when paperpilot.vertex.vertex_enabled() -- the help assistant
    # otherwise streams "draft" (Claude) through the Gateway, unchanged.
    "assist_vertex": os.environ.get("MODEL_ASSIST_VERTEX", "google/gemini-2.5-flash"),
}
