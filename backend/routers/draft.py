"""Draft router: stream a paper draft section-by-section as SSE.

POST /draft accepts a research summary plus a target venue and streams the
abstract, introduction, related-work, and method sections as they are
generated. Each token delta is pushed as a Server-Sent Event so the
frontend can render the draft live.

Event types emitted (the SSE `event:` field):
  - "delta": a streamed text chunk. data = {"section", "text"}.
  - "section": a section just finished. data carries the final text,
    resolved citations, and any unsanctioned arxiv IDs that were stripped.
  - "done": the whole draft finished. data = {"session_id", "sections"}.
  - "error": generation failed. data = {"message"}.

The arxiv citation candidates are sourced from Supabase pgvector (not the
legacy ClickHouse path); see backend.services.draft_service.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, AsyncIterator

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool

from backend.auth import AuthUser, CurrentUser
from backend import quotas
from backend.byok import OptionalLLMKey
from backend.services.draft_service import draft_paper_supabase
from paperpilot import trace
from paperpilot.draft import SECTIONS, DraftSection
from paperpilot.llm_ingest import ResearchSummary

router = APIRouter(tags=["draft"])


class VenuePayload(BaseModel):
    """Target venue for the draft. Only name and scope drive the prompts."""

    name: str
    scope: str = ""
    id: str = ""
    url: str = ""
    deadline: str | None = None
    fit_score: float = 0.0
    days_until_deadline: int = 0


class DraftRequest(BaseModel):
    """Request body for POST /draft."""

    summary: ResearchSummary
    venue: VenuePayload
    session_id: str | None = Field(default=None)
    candidate_limit: int = 10


def _sse(event: str, data: dict[str, Any]) -> dict[str, Any]:
    """Format an SSE message for EventSourceResponse."""
    return {"event": event, "data": json.dumps(data, default=str)}


def _section_payload(section: DraftSection) -> dict[str, Any]:
    """Serialize a finished DraftSection (citations -> plain dicts)."""
    return {
        "section": section.name,
        "text": section.text,
        "citations": [asdict(c) for c in section.citations],
        "stripped_ids": section.stripped_ids,
    }


@router.post("/draft", response_model=None)
async def draft(
    req: DraftRequest,
    user: AuthUser = CurrentUser,
    _: None = OptionalLLMKey,
) -> EventSourceResponse:
    """Stream the paper draft section-by-section as Server-Sent Events.

    A new trace session is started for the run when the caller does not
    supply one, bound to the authenticated user so trace rows are
    tenant-scoped.
    """
    # Output-bounded at 900 tokens a section, so Merit absorbs it for callers
    # who brought no key of their own -- capped, because absorbing it is not the
    # same as absorbing it without limit.
    quotas.admit(user.id, quotas.DRAFT)
    session_id = req.session_id or trace.new_session(user.id)
    venue_dict = req.venue.model_dump()

    async def event_stream() -> AsyncIterator[dict[str, Any]]:
        """Drive the blocking generator off the event loop and emit SSE.

        The drafter is a synchronous generator that yields (section, delta)
        as tokens arrive and returns the assembled section map on
        completion. iterate_in_threadpool runs each step on a worker thread
        so the blocking Gateway stream never stalls the event loop. The
        wrapper captures the generator's return value (only available at
        StopIteration) so the final per-section payloads and the assembled
        summary can be emitted once streaming ends.
        """
        wrapped = _DraftGenerator(
            draft_paper_supabase(
                req.summary,
                venue_dict,
                session_id,
                candidate_limit=req.candidate_limit,
            )
        )
        try:
            async for section_name, delta in iterate_in_threadpool(wrapped):
                yield _sse("delta", {"section": section_name, "text": delta})
            # Per-section payloads (final text, citations, stripped IDs) are
            # only known after the generator returns; emit them here in order.
            for name in (n for n in SECTIONS if n in wrapped.sections):
                yield _sse("section", _section_payload(wrapped.sections[name]))
            yield _sse(
                "done",
                {
                    "session_id": session_id,
                    "sections": {
                        name: _section_payload(sec)
                        for name, sec in wrapped.sections.items()
                    },
                },
            )
        except Exception as exc:  # noqa: BLE001 -- surface to the client, end stream
            yield _sse("error", {"message": str(exc)})

    return EventSourceResponse(event_stream())


class _DraftGenerator:
    """Wrap the draft generator to capture per-section results as they finish.

    The underlying generator yields (section_name, delta) and returns the
    assembled dict on StopIteration. A plain iterator drops that return
    value, so this wrapper intercepts StopIteration, stores the returned
    sections, and exposes them via `.sections` for the SSE layer.
    """

    def __init__(
        self, gen: Any
    ) -> None:
        self._gen = gen
        self.sections: dict[str, DraftSection] = {}

    def __iter__(self) -> "_DraftGenerator":
        return self

    def __next__(self) -> tuple[str, str]:
        try:
            return next(self._gen)
        except StopIteration as stop:
            if isinstance(stop.value, dict):
                self.sections = stop.value
            raise
