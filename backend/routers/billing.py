"""Billing: Stripe Checkout for the paid O-1A dossier + the webhook that grants it.

Merit's own revenue comes from unlocking the attorney-ready dossier PDF -- a
one-time purchase, distinct from the caller's BYOK model usage. Checkout creates
a Stripe session; the signature-verified webhook marks the purchase paid; the
dossier route (``backend.routers.evidence``) gates on the resulting entitlement.

All Stripe config is read from the environment. When STRIPE_SECRET_KEY is unset
the endpoints return 503 rather than 500, so the app runs unconfigured.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from backend import entitlements
from backend.auth import AuthUser, CurrentUser
from paperpilot import supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

_STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
_STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
_STRIPE_PRICE_DOSSIER = os.environ.get("STRIPE_PRICE_DOSSIER")
# Where Stripe returns the caller after checkout.
_FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
# Mirrored from the Stripe price purely for the ledger row.
_DOSSIER_AMOUNT_CENTS = 9900


def _stripe():
    """Return the configured Stripe module, or 503 when billing isn't set up."""
    if not _STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured.",
        )
    import stripe

    stripe.api_key = _STRIPE_SECRET_KEY
    return stripe


class CheckoutResponse(BaseModel):
    url: str


class EntitlementResponse(BaseModel):
    product: str
    entitled: bool


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(user: AuthUser = CurrentUser) -> CheckoutResponse:
    """Start a Stripe Checkout session to buy the dossier unlock."""
    if entitlements.has_entitlement(user.id, entitlements.DOSSIER):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already own the full dossier.",
        )
    if not _STRIPE_PRICE_DOSSIER:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing price is not configured.",
        )
    stripe = _stripe()
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": _STRIPE_PRICE_DOSSIER, "quantity": 1}],
            client_reference_id=user.id,
            metadata={"user_id": user.id, "product": entitlements.DOSSIER},
            success_url=f"{_FRONTEND_URL}/track?purchased=dossier",
            cancel_url=f"{_FRONTEND_URL}/track?checkout=cancelled",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("stripe checkout create failed for user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout.",
        ) from exc

    supabase_client.record_pending_purchase(
        user_id=user.id,
        product=entitlements.DOSSIER,
        stripe_session_id=session.id,
        amount_cents=_DOSSIER_AMOUNT_CENTS,
    )
    return CheckoutResponse(url=session.url)


@router.get("/entitlement", response_model=EntitlementResponse)
def get_entitlement(
    product: str = entitlements.DOSSIER, user: AuthUser = CurrentUser
) -> EntitlementResponse:
    """Whether the caller owns ``product``."""
    return EntitlementResponse(
        product=product, entitled=entitlements.has_entitlement(user.id, product)
    )


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict:
    """Grant the entitlement when Stripe confirms a completed checkout.

    Verifies the Stripe signature so a forged request cannot grant a purchase.
    """
    if not _STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook is not configured.",
        )
    stripe = _stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, _STRIPE_WEBHOOK_SECRET)
    except Exception as exc:  # noqa: BLE001 -- bad signature or malformed payload
        logger.warning("stripe webhook verification failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature."
        ) from exc

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        if session.get("payment_status") == "paid":
            updated = supabase_client.mark_purchase_paid(
                stripe_session_id=session["id"],
                stripe_payment_intent=session.get("payment_intent"),
            )
            if updated:
                logger.info(
                    "purchase paid: user=%s session=%s",
                    session.get("client_reference_id"),
                    session["id"],
                )
    return {"received": True}
