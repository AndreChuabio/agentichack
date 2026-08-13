"""Market router: user profile + outreach drafting endpoints.

All endpoints require authentication and are scoped to the caller's user.id.
Persistence lives in backend.services.market_service over Supabase; LLM and
Senso generation is delegated to the existing paperpilot.outreach pipeline.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from backend import quotas
from backend.auth import AuthUser, CurrentUser
from backend.byok import RequireLLMKey
from backend.services import enrich_service, market_service, resume_service
from paperpilot import trace

router = APIRouter(prefix="/market", tags=["market"])


class ProfileOut(BaseModel):
    """A user's outreach profile."""

    name: str = ""
    title: str = ""
    about: str = ""
    voice_tone: str = ""
    github_url: str = ""
    linkedin_url: str = ""
    scholar_url: str = ""
    site_url: str = ""
    resume_text: str = ""
    selected_repos: list[str] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    """Mutable profile fields. Omitted fields are left unchanged."""

    name: str | None = None
    title: str | None = None
    about: str | None = None
    voice_tone: str | None = None
    github_url: str | None = None
    linkedin_url: str | None = None
    scholar_url: str | None = None
    site_url: str | None = None
    resume_text: str | None = None
    selected_repos: list[str] | None = None


class OutreachGenerateRequest(BaseModel):
    """Request body for generating outreach drafts."""

    purpose: str = Field(..., description="VISA, CAREER, NETWORK, BRAND, or SERVICE")
    context: str = Field("", description="Author context to seed the drafts")


class DraftCardOut(BaseModel):
    """One generated draft card for a single channel."""

    channel: str
    content_type_id: str
    sample_job_id: str
    markdown: str
    draft_id: str = ""
    error: str | None = None


class OutreachLogRow(BaseModel):
    """A recorded outreach event (generated or sent)."""

    id: int
    ts: str | None = None
    purpose: str
    channel: str
    content_type_id: str
    sample_job_id: str
    draft_id: str
    posted: bool
    recipient_name: str = ""
    recipient_contact: str = ""


class PersonOut(BaseModel):
    """A suggested person or organization to reach out to."""

    name: str
    detail: str = ""
    url: str = ""
    email: str = ""


class PeopleResponse(BaseModel):
    """People suggestions plus whether the discovery source is configured.

    reason is populated when configured is False, explaining that contact
    discovery is an optional integration rather than a broken feature.
    """

    configured: bool
    people: list[PersonOut]
    reason: str = ""


class PeopleRequest(BaseModel):
    """Request body for people discovery."""

    purpose: str = Field(..., description="VISA, CAREER, NETWORK, BRAND, or SERVICE")
    context: str = Field("", description="Who/what you are reaching about")


class SentRequest(BaseModel):
    """Request body for recording a draft sent to a recipient."""

    purpose: str
    channel: str = ""
    recipient_name: str = ""
    recipient_contact: str = ""
    draft_id: str = ""


def _profile_out(profile: market_service.Profile) -> ProfileOut:
    """Map a service Profile to the API response model (drops user_id)."""
    return ProfileOut(
        name=profile.name,
        title=profile.title,
        about=profile.about,
        voice_tone=profile.voice_tone,
        github_url=profile.github_url,
        linkedin_url=profile.linkedin_url,
        scholar_url=profile.scholar_url,
        site_url=profile.site_url,
        resume_text=profile.resume_text,
        selected_repos=list(profile.selected_repos),
    )


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: AuthUser = CurrentUser) -> ProfileOut:
    """Return the caller's profile, with empty defaults if none exists."""
    return _profile_out(market_service.get_profile(user.id))


@router.put("/profile", response_model=ProfileOut)
def put_profile(
    body: ProfileUpdate, user: AuthUser = CurrentUser
) -> ProfileOut:
    """Upsert the caller's profile and return the stored result."""
    fields = body.model_dump(exclude_none=True)
    profile = market_service.upsert_profile(user.id, fields)
    return _profile_out(profile)


@router.post("/outreach/generate", response_model=list[DraftCardOut])
def generate_outreach(
    body: OutreachGenerateRequest,
    user: AuthUser = CurrentUser,
    _: None = RequireLLMKey,
) -> list[DraftCardOut]:
    """Generate draft cards for a purpose and log each event for the caller."""
    try:
        cards: list[dict[str, Any]] = market_service.generate_outreach(
            user_id=user.id, purpose=body.purpose, context=body.context
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return [DraftCardOut(**card) for card in cards]


@router.get("/outreach/log", response_model=list[OutreachLogRow])
def get_outreach_log(
    limit: int = 50, user: AuthUser = CurrentUser
) -> list[OutreachLogRow]:
    """Return the caller's recent outreach_log rows, newest first."""
    rows = market_service.list_outreach_log(user.id, limit=limit)
    return [OutreachLogRow(**row) for row in rows]


@router.post("/outreach/people", response_model=PeopleResponse)
def suggest_people(
    body: PeopleRequest, user: AuthUser = CurrentUser
) -> PeopleResponse:
    """Suggest people/orgs to reach for a purpose + context via web search."""
    result = market_service.suggest_people(
        user_id=user.id, purpose=body.purpose, context=body.context
    )
    return PeopleResponse(
        configured=result["configured"],
        people=[PersonOut(**p) for p in result["people"]],
        reason=result.get("reason", ""),
    )


@router.post("/outreach/sent", status_code=status.HTTP_204_NO_CONTENT)
def record_sent(body: SentRequest, user: AuthUser = CurrentUser) -> None:
    """Record that the caller sent a draft to a recipient (posted=True)."""
    market_service.log_sent(
        user_id=user.id,
        purpose=body.purpose,
        channel=body.channel,
        recipient_name=body.recipient_name,
        recipient_contact=body.recipient_contact,
        draft_id=body.draft_id,
    )


class ResumeTextResponse(BaseModel):
    """Extracted resume text for the user to review before saving."""

    resume_text: str


@router.post("/profile/resume", response_model=ResumeTextResponse)
async def upload_resume(
    file: UploadFile = File(...),
    user: AuthUser = CurrentUser,
) -> ResumeTextResponse:
    """Extract text from an uploaded PDF or .docx resume.

    Reads at most MAX_BYTES so an oversized upload is refused on the bytes
    actually received rather than on a content-length header the client set.
    Does not write the profile: the user reviews the text and saves it.

    Counted against ENRICH alongside autofill. Parsing spends no model call, so
    the cap is not about token cost -- it bounds an endpoint that otherwise lets
    one account buffer and parse unlimited multi-megabyte uploads. Counting both
    enrichment paths in one bucket also keeps the cap meaningful: a limit
    computed from half the traffic is not a limit.
    """
    quotas.enforce(user.id, quotas.ENRICH)
    session_id = trace.new_session(user.id)
    with trace.step(session_id, "profile_enrich", user_id=user.id, source="resume") as ctx:
        data = await file.read(resume_service.MAX_BYTES)
        text = resume_service.extract_text(file.filename or "", data)
        ctx["chars"] = len(text)
    return ResumeTextResponse(resume_text=text)


class AutofillRequest(BaseModel):
    """The links already on the form."""

    github_url: str = ""
    linkedin_url: str = ""
    scholar_url: str = ""
    site_url: str = ""


class SourceStatusOut(BaseModel):
    """Whether one pasted link could be read, and why not when it could not."""

    source: str
    ok: bool
    detail: str = ""


class AutofillResponse(BaseModel):
    """Proposed values the user accepts field by field, plus source statuses."""

    proposed: dict[str, str]
    sources: list[SourceStatusOut]


@router.post("/profile/autofill", response_model=AutofillResponse)
def autofill_profile(
    body: AutofillRequest,
    user: AuthUser = CurrentUser,
    _: None = RequireLLMKey,
) -> AutofillResponse:
    """Propose profile fields from pasted links. Never writes the profile."""
    quotas.enforce(user.id, quotas.ENRICH)
    result = enrich_service.autofill(user.id, body.model_dump())
    return AutofillResponse(
        proposed=result.proposed,
        sources=[SourceStatusOut(**vars(s)) for s in result.sources],
    )
