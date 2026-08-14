"""Bring-your-own-key: bind the caller's gateway key to this request.

Merit never stores a user's API key. The browser holds it, sends it on each
request in the X-LLM-Key header, and this dependency binds it to the request
context for the duration of the call. Nothing writes it to a table, a log, or a
response body. See paperpilot/redaction.py for the scrubbing that enforces
the log half of that promise.

The key is a Vercel AI Gateway key, not a provider key: Merit calls Google for
ingest, Anthropic for drafting, and OpenAI for embeddings, so no single provider
key can run the pipeline.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from paperpilot import gateway


async def require_llm_key(
    x_llm_key: str | None = Header(default=None),
) -> None:
    """FastAPI dependency: bind the caller's gateway key, or reject the request."""
    if not x_llm_key or not x_llm_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This surface runs on your own API key. Supply a Vercel AI "
                "Gateway key in the X-LLM-Key header."
            ),
        )
    gateway.set_request_key(x_llm_key.strip())


RequireLLMKey = Depends(require_llm_key)


async def optional_llm_key(
    x_llm_key: str | None = Header(default=None),
) -> None:
    """Bind the caller's key when they sent one, and never reject when they did not.

    The split exists because the two halves of the product have different cost
    shapes. Reading a repo is input-token-dominated -- github_ingest caps a
    bundle at 600K tokens -- so a surge of users on Merit's key is a bill that
    grows without a natural ceiling, and those surfaces keep require_llm_key.
    Drafting an email or embedding a summary is output-bounded at a few hundred
    tokens, so Merit absorbing it costs fractions of a cent and is worth it to
    have the product work on first visit.

    Callers who DO supply a key are spending their own money, which is why
    quota_unless_byok below exempts them from the cap.
    """
    if x_llm_key and x_llm_key.strip():
        gateway.set_request_key(x_llm_key.strip())


OptionalLLMKey = Depends(optional_llm_key)


def byok_in_effect() -> bool:
    """Whether this request is spending the caller's own key rather than Merit's."""
    return bool(gateway.current_request_key())
