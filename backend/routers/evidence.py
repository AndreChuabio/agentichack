"""Evidence router: O-1A evidence ledger CRUD, narratives, and PDF dossier.

Wraps ``backend.services.evidence_service`` over the FastAPI + Supabase auth
layer. Every endpoint is scoped to the authenticated caller's ``user.id``.

  GET    /evidence                       -> grouped ledger + "X of 8 satisfied"
  POST   /evidence                       -> declare a new evidence item
  PATCH  /evidence/{id}                  -> update mutable fields
  DELETE /evidence/{id}                  -> hard-delete an item
  POST   /evidence/{criterion}/narrative -> draft a petition-quality narrative
  POST   /dossier                        -> build the reportlab PDF dossier

The eight USCIS O-1A criteria, narrative drafting, and PDF rendering are
reused from the paperpilot pipeline modules via the service layer.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend import entitlements, quotas
from backend.auth import AuthUser, CurrentUser
from backend.services import evidence_service
from paperpilot.outreach.evidence import USCIS_O1A_CRITERIA, EvidenceItem

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evidence"])

_TOTAL_CRITERIA = len(USCIS_O1A_CRITERIA)


class EvidenceItemOut(BaseModel):
    """One declared evidence item as returned to the client."""

    id: str
    criterion: str
    title: str
    description: str
    evidence_url: str
    evidence_date: Optional[date]
    declared_at: datetime
    status: str
    metadata: dict


class CriterionGroup(BaseModel):
    """All declared items for one of the eight O-1A criteria."""

    criterion: str
    label: str
    satisfied: bool
    items: list[EvidenceItemOut]


class LedgerResponse(BaseModel):
    """The full evidence ledger grouped by criterion with a satisfied count."""

    criteria: list[CriterionGroup]
    satisfied_count: int
    total: int


class EvidenceCreate(BaseModel):
    """Body for POST /evidence."""

    criterion: str
    title: str
    description: str = ""
    evidence_url: str = ""
    evidence_date: Optional[date] = None
    status: str = "draft"
    metadata: dict = Field(default_factory=dict)


class EvidenceUpdate(BaseModel):
    """Body for PATCH /evidence/{id}. Only provided fields are updated."""

    criterion: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    evidence_url: Optional[str] = None
    evidence_date: Optional[date] = None
    status: Optional[str] = None
    metadata: Optional[dict] = None


class NarrativeRequest(BaseModel):
    """Body for POST /evidence/{criterion}/narrative."""

    session_id: Optional[str] = None


class NarrativeResponse(BaseModel):
    """A drafted per-criterion petition narrative."""

    criterion: str
    narrative: str


class DossierRequest(BaseModel):
    """Body for POST /dossier."""

    session_id: Optional[str] = None


def _to_out(item: EvidenceItem) -> EvidenceItemOut:
    """Map a service EvidenceItem to its API representation."""
    return EvidenceItemOut(
        id=item.id,
        criterion=item.criterion,
        title=item.title,
        description=item.description,
        evidence_url=item.evidence_url,
        evidence_date=item.evidence_date,
        declared_at=item.declared_at,
        status=item.status,
        metadata=item.metadata or {},
    )


@router.get("/evidence", response_model=LedgerResponse)
def list_ledger(user: AuthUser = CurrentUser) -> LedgerResponse:
    """Return the caller's evidence grouped by criterion with a satisfied count."""
    grouped = evidence_service.evidence_by_criterion(user.id)
    criteria: list[CriterionGroup] = []
    satisfied_count = 0
    for key, label in USCIS_O1A_CRITERIA:
        items = grouped.get(key, [])
        satisfied = len(items) > 0
        if satisfied:
            satisfied_count += 1
        criteria.append(
            CriterionGroup(
                criterion=key,
                label=label,
                satisfied=satisfied,
                items=[_to_out(i) for i in items],
            )
        )
    return LedgerResponse(
        criteria=criteria,
        satisfied_count=satisfied_count,
        total=_TOTAL_CRITERIA,
    )


@router.post(
    "/evidence", response_model=EvidenceItemOut, status_code=status.HTTP_201_CREATED
)
def create_item(req: EvidenceCreate, user: AuthUser = CurrentUser) -> EvidenceItemOut:
    """Declare a new evidence item against one of the eight O-1A criteria."""
    try:
        item = evidence_service.declare_evidence(
            user_id=user.id,
            criterion=req.criterion,
            title=req.title,
            description=req.description,
            evidence_url=req.evidence_url,
            evidence_date=req.evidence_date,
            status=req.status,
            metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _to_out(item)


@router.patch("/evidence/{item_id}", response_model=EvidenceItemOut)
def update_item(
    item_id: str, req: EvidenceUpdate, user: AuthUser = CurrentUser
) -> EvidenceItemOut:
    """Update mutable fields of one of the caller's evidence items."""
    fields = req.model_dump(exclude_unset=True)
    try:
        item = evidence_service.update_evidence(user.id, item_id, **fields)
    except ValueError as exc:
        msg = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in msg
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=msg) from exc
    return _to_out(item)


@router.delete("/evidence/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: str, user: AuthUser = CurrentUser) -> Response:
    """Hard-delete one of the caller's evidence items."""
    removed = evidence_service.delete_evidence(user.id, item_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"evidence id={item_id!r} not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/evidence/{criterion}/narrative", response_model=NarrativeResponse)
def draft_narrative(
    criterion: str,
    req: NarrativeRequest | None = None,
    user: AuthUser = CurrentUser,
) -> NarrativeResponse:
    """Draft a petition-quality narrative for one O-1A criterion."""
    quotas.enforce(user.id, quotas.NARRATIVE)
    session_id = req.session_id if req else None
    try:
        narrative = evidence_service.draft_criterion_narrative(
            user_id=user.id, criterion=criterion, session_id=session_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        logger.exception("narrative drafting failed for criterion=%s", criterion)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return NarrativeResponse(criterion=criterion, narrative=narrative)


@router.post("/dossier")
def build_dossier(
    req: DossierRequest | None = None, user: AuthUser = CurrentUser
) -> Response:
    """Build the O-1A evidence dossier PDF and return it as application/pdf.

    Entitlement is checked before the quota, and the quota that applies depends
    on who is paying. A customer who bought the unlock hitting a 429 that blames
    Merit's API key cap is both wrong and insulting, so paying callers get an
    abuse ceiling instead of the free cost cap. When the paywall is dark
    (STRIPE_PRICE_DOSSIER unset) every caller is entitled and Merit is still
    paying, so the free cap stays in force.
    """
    paywalled = entitlements.billing_enabled(entitlements.DOSSIER)
    try:
        entitled = entitlements.has_entitlement(user.id, entitlements.DOSSIER)
    except Exception as exc:  # noqa: BLE001
        # A ledger blip must not read as a bare 500 on a download somebody paid
        # for. Say what failed and that retrying is the right move.
        logger.exception("entitlement lookup failed for user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="We could not verify your purchase. Please try again.",
        ) from exc
    if not entitled:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Unlock the full dossier to download it.",
        )
    quotas.enforce(user.id, quotas.DOSSIER_PAID if paywalled else quotas.DOSSIER)
    session_id = req.session_id if req else None
    try:
        pdf_bytes = evidence_service.build_dossier(user.id, session_id=session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        logger.exception("dossier build failed for user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    filename = evidence_service.dossier_filename(user.id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
