"""First-party Gemini via Vertex AI (Google Cloud).

When ``VERTEX_PROJECT`` is set, the Merit-dime surfaces -- repo ingest and
the help assistant -- call Gemini directly on Vertex AI -- a Google Cloud
product and the Gemini API -- instead of proxying the model through the
Vercel AI Gateway. This makes the "built with Google Cloud + the Gemini
API" claim first-party and true. BYOK surfaces (paper drafting, embeddings)
are untouched -- they keep routing through the Gateway regardless of this
flag.

Auth uses Application Default Credentials, i.e. the service-account file pointed
to by ``GOOGLE_APPLICATION_CREDENTIALS``. Nothing else in the pipeline changes:
when ``VERTEX_PROJECT`` is unset the caller falls back to the gateway path.

Every call records its token usage to the gemini_usage Supabase table plus a
structured log line via _record_usage, so the app's Google Cloud usage is
verifiable rather than only inferred from code.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT")
_VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")


def vertex_enabled() -> bool:
    """True when Merit-dime surfaces should run first-party on Vertex AI."""
    return bool(_VERTEX_PROJECT)


def _record_usage(
    surface: str, model: str, tokens_in: int, tokens_out: int, tenant_id: str | None
) -> None:
    """Log and persist one Vertex call's token usage. Never raises.

    A usage-logging failure must not break the caller's generation, matching
    paperpilot.trace.log_event's best-effort contract. Skips the Supabase
    write (but still logs) when SUPABASE_DB_URL is unset, e.g. local dev.
    """
    logger.info(
        "gemini_usage surface=%s model=%s tokens_in=%d tokens_out=%d tenant_id=%s",
        surface,
        model,
        tokens_in,
        tokens_out,
        tenant_id or "-",
    )
    if not os.environ.get("SUPABASE_DB_URL"):
        return
    try:
        from paperpilot.supabase_client import record_gemini_usage

        record_gemini_usage(surface, model, tokens_in, tokens_out, tenant_id)
    except Exception:  # noqa: BLE001 -- best-effort; never fail the caller
        logger.exception(
            "gemini_usage insert failed surface=%s model=%s", surface, model
        )


@dataclass
class GeminiResult:
    """Normalized Gemini response so callers stay backend-agnostic."""

    text: str
    tokens_in: int
    tokens_out: int
    finish_reason: str


@lru_cache(maxsize=1)
def _client() -> Any:
    """Return a cached Vertex-mode google-genai client.

    Imported lazily so the dependency is only required when Vertex is enabled.
    """
    from google import genai

    return genai.Client(
        vertexai=True, project=_VERTEX_PROJECT, location=_VERTEX_LOCATION
    )


def generate_json(
    model: str,
    system_prompt: str,
    user_content: str,
    surface: str,
    tenant_id: str | None,
    max_output_tokens: int = 8000,
    temperature: float = 0.2,
) -> GeminiResult:
    """Run one Gemini generation on Vertex AI and return text + token usage.

    ``model`` may carry the gateway-style ``google/`` prefix; Vertex uses the
    bare model id (e.g. ``gemini-2.5-flash``). Vertex honors native JSON mode,
    so we request ``application/json`` directly rather than relying on prompt
    coaxing. ``surface`` (e.g. "ingest") and ``tenant_id`` (the caller's user
    id, or None outside a bound session) are recorded against this call in
    gemini_usage.
    """
    from google.genai import types

    model_id = model.split("/", 1)[-1]
    resp = _client().models.generate_content(
        model=model_id,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
        ),
    )

    usage = resp.usage_metadata
    finish_reason = ""
    if resp.candidates and resp.candidates[0].finish_reason is not None:
        finish_reason = str(resp.candidates[0].finish_reason)

    tokens_in = getattr(usage, "prompt_token_count", 0) or 0
    tokens_out = getattr(usage, "candidates_token_count", 0) or 0
    _record_usage(surface, model_id, tokens_in, tokens_out, tenant_id)

    return GeminiResult(
        text=resp.text or "{}",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        finish_reason=finish_reason,
    )


def generate_text_stream(
    model: str,
    system_prompt: str,
    user_content: str,
    surface: str,
    tenant_id: str | None,
    max_output_tokens: int = 700,
    temperature: float = 0.4,
) -> Iterator[str]:
    """Stream a plain-text Gemini generation on Vertex AI, yielding deltas.

    Backs the help assistant's token-by-token streaming. Records usage once
    the stream is exhausted -- the Vertex SDK reports cumulative
    ``usage_metadata`` on each chunk, so the last chunk that carries it holds
    the final token counts.
    """
    from google.genai import types

    model_id = model.split("/", 1)[-1]
    tokens_in = 0
    tokens_out = 0
    stream = _client().models.generate_content_stream(
        model=model_id,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text
        usage = chunk.usage_metadata
        if usage is not None:
            tokens_in = getattr(usage, "prompt_token_count", 0) or 0
            tokens_out = getattr(usage, "candidates_token_count", 0) or 0

    _record_usage(surface, model_id, tokens_in, tokens_out, tenant_id)
