"""First-party Gemini via Vertex AI (Google Cloud).

When ``VERTEX_PROJECT`` is set, the repo-ingest step calls Gemini directly on
Vertex AI -- a Google Cloud product and the Gemini API -- instead of proxying
the model through the Vercel AI Gateway. This makes the "built with Google
Cloud + the Gemini API" claim first-party and true.

Auth uses Application Default Credentials, i.e. the service-account file pointed
to by ``GOOGLE_APPLICATION_CREDENTIALS``. Nothing else in the pipeline changes:
when ``VERTEX_PROJECT`` is unset the caller falls back to the gateway path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT")
_VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")


def vertex_enabled() -> bool:
    """True when repo ingest should run first-party on Vertex AI."""
    return bool(_VERTEX_PROJECT)


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
    from google.genai import types

    # Bounded rather than the SDK default: a hung Vertex call would otherwise
    # pin one of the limited worker threads indefinitely. Milliseconds.
    return genai.Client(
        vertexai=True,
        project=_VERTEX_PROJECT,
        location=_VERTEX_LOCATION,
        http_options=types.HttpOptions(timeout=180_000),
    )


def generate_json(
    model: str,
    system_prompt: str,
    user_content: str,
    max_output_tokens: int = 8000,
    temperature: float = 0.2,
) -> GeminiResult:
    """Run one Gemini generation on Vertex AI and return text + token usage.

    ``model`` may carry the gateway-style ``google/`` prefix; Vertex uses the
    bare model id (e.g. ``gemini-2.5-flash``). Vertex honors native JSON mode,
    so we request ``application/json`` directly rather than relying on prompt
    coaxing.
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

    return GeminiResult(
        text=resp.text or "{}",
        tokens_in=getattr(usage, "prompt_token_count", 0) or 0,
        tokens_out=getattr(usage, "candidates_token_count", 0) or 0,
        finish_reason=finish_reason,
    )
