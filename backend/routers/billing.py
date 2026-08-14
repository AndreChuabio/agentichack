"""Billing: Stripe Checkout for the paid O-1A dossier + the webhook that grants it.

Merit's own revenue comes from unlocking the attorney-ready dossier PDF -- a
one-time purchase, distinct from the caller's BYOK model usage. Checkout creates
a Stripe session; the signature-verified webhook marks the purchase paid; the
dossier route (``backend.routers.evidence``) gates on the resulting entitlement.

All Stripe config is read from the environment, at call time rather than at
import. When STRIPE_SECRET_KEY is unset the endpoints return 503 rather than
500, so the app runs unconfigured.

The webhook is deliberately the only place a purchase is granted, and it is
written to be self-sufficient: a charge Stripe reports as paid grants the
entitlement even when no pending row exists for the session, and anything that
still fails to grant is logged with the marker STRIPE PAID BUT NOT GRANTED.
Money captured with nothing delivered is the one failure here that must never
be silent.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from backend import entitlements
from backend.auth import AuthUser, CurrentUser
from paperpilot import supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

# Fallback ledger amount for the pending row, used only until Stripe reports
# the real charge. The grant writes session.amount_total instead, so the ledger
# reflects what was actually captured rather than a constant that drifts from
# the Stripe price the moment the price changes.
_DOSSIER_AMOUNT_CENTS = 9900

# How far back to look for an in-flight checkout worth resuming. Long enough to
# cover webhook lag and a user who tabbed away, short enough that a genuinely
# abandoned session does not block a fresh purchase all day.
_PENDING_REUSE_WINDOW = timedelta(minutes=30)

# Both of these mean "Stripe has the money". checkout.session.completed fires
# for a card, which settles synchronously; async_payment_succeeded fires for a
# payment method that completes the session as unpaid and settles later. Handled
# identically, because the grant condition is payment_status == "paid" either way.
_PAID_EVENTS = frozenset(
    {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
)


# ---------------------------------------------------------------------------
# Configuration (read at call time, never at import)
#
# backend.main calls load_dotenv() and imports this router. A module-level read
# freezes whatever the environment held at import, which in a dotenv-driven
# environment is nothing -- leaving these endpoints 503ing while
# entitlements.billing_enabled() (which does read at call time) reports the
# paywall as live. That combination paywalls the dossier with no way to pay.
# ---------------------------------------------------------------------------

def _secret_key() -> str | None:
    """The Stripe API secret key, or None when billing is unconfigured."""
    return os.environ.get("STRIPE_SECRET_KEY")


def _webhook_secret() -> str | None:
    """The signing secret used to verify webhook payloads."""
    return os.environ.get("STRIPE_WEBHOOK_SECRET")


def _price_dossier() -> str | None:
    """The Stripe price id for the dossier unlock."""
    return os.environ.get("STRIPE_PRICE_DOSSIER")


def _frontend_url() -> str:
    """Where Stripe returns the caller after checkout."""
    return os.environ.get("FRONTEND_URL", "http://localhost:3000")


def _stripe() -> Any:
    """Return the configured Stripe module, or 503 when billing isn't set up."""
    secret = _secret_key()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured.",
        )
    import stripe

    stripe.api_key = secret
    return stripe


def _as_mapping(obj: Any) -> dict[str, Any]:
    """Normalise one node of a Stripe payload into a plain dict.

    Every read of a Stripe payload in this module goes through this first, and
    the result is then only ever touched with ``.get()``. That is not
    fastidiousness, it is the bug that took a live $99 payment and granted
    nothing:

    As of stripe-python 15, StripeObject no longer subclasses dict. It has no
    ``.get()``, and BOTH remaining access styles raise on a key that is absent
    -- ``obj.missing`` raises AttributeError via __getattr__, ``obj["missing"]``
    raises KeyError. Since optional fields (payment_intent, client_reference_id,
    metadata) are genuinely absent from real payloads, any direct access is a
    500 waiting for the right customer. Normalising to a plain dict makes a
    missing key None instead of an exception, everywhere, permanently.

    ``to_dict()`` is the public converter (``to_dict_recursive()`` does not
    exist on 15.x -- it is private ``_to_dict_recursive``, and calling the
    public-looking name raises the very AttributeError this guards against).
    It is applied per level rather than trusted to recurse, so a plain dict, a
    shallow conversion, and a fully converted tree all come out the same.
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    # A real attribute on StripeObject, so this never reaches __getattr__.
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            converted = to_dict()
        except Exception:  # noqa: BLE001 -- an unreadable payload is not a crash
            logger.exception("could not convert a stripe payload node to a dict")
            return {}
        if isinstance(converted, dict):
            return converted
    return {}


class CheckoutResponse(BaseModel):
    url: str


class EntitlementResponse(BaseModel):
    product: str
    entitled: bool


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def _resume_pending_checkout(stripe: Any, user_id: str) -> str | None:
    """Return the URL of this caller's still-open recent checkout, if any.

    The already-entitled 409 in ``create_checkout`` only fires once the webhook
    has landed. In the window before that, a second click would create a second
    session and capture a second $99. Resuming the existing session closes that
    window; a session Stripe already reports as complete raises 409 instead,
    because the money is in and only the grant is outstanding.

    Returns None when there is nothing safe to resume, in which case the caller
    creates a fresh session.
    """
    since = datetime.now(timezone.utc) - _PENDING_REUSE_WINDOW
    try:
        session_id = supabase_client.recent_pending_purchase(
            user_id=user_id, product=entitlements.DOSSIER, since=since
        )
    except Exception:  # noqa: BLE001 -- a lookup blip must not block checkout
        logger.exception("pending purchase lookup failed for user=%s", user_id)
        return None
    if not session_id:
        return None

    try:
        session = _as_mapping(stripe.checkout.Session.retrieve(session_id))
    except Exception:  # noqa: BLE001 -- unknown session, treat as nothing to resume
        logger.exception("could not retrieve pending stripe session=%s", session_id)
        return None

    state = session.get("status")
    url = session.get("url")
    if state == "open" and url:
        logger.info("resuming open checkout session=%s user=%s", session_id, user_id)
        return url
    if state == "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your payment is being confirmed. Refresh in a moment.",
        )
    return None


def _create_session(stripe: Any, user_id: str, price: str) -> dict[str, Any]:
    """Create the Stripe Checkout session for the dossier unlock.

    payment_method_types is pinned to card on purpose. Live-mode dynamic
    payment methods (Link, Cash App, Klarna) complete a session as "unpaid" and
    settle asynchronously, which is a materially different money path; the
    webhook now handles it, but the launch surface stays on the method that
    settles synchronously until that path has live evidence behind it.

    The idempotency key is stable per user per day, so a double click or a
    retried request replays one session rather than minting a second charge.
    """
    params: dict[str, Any] = {
        "mode": "payment",
        "payment_method_types": ["card"],
        "line_items": [{"price": price, "quantity": 1}],
        "client_reference_id": user_id,
        "metadata": {"user_id": user_id, "product": entitlements.DOSSIER},
        "success_url": f"{_frontend_url()}/track?purchased=dossier",
        "cancel_url": f"{_frontend_url()}/track?checkout=cancelled",
    }
    idempotency_key = f"dossier-{user_id}-{date.today().isoformat()}"
    try:
        session = _as_mapping(
            stripe.checkout.Session.create(**params, idempotency_key=idempotency_key)
        )
        if not session.get("url"):
            # The key replayed a session that is no longer open -- an earlier
            # attempt today was expired after its ledger write failed. An
            # expired session was never charged, so a fresh one cannot double
            # charge, and without this the button stays dead until midnight.
            logger.warning(
                "idempotent replay returned a closed session for user=%s", user_id
            )
            session = _as_mapping(stripe.checkout.Session.create(**params))
    except Exception as exc:  # noqa: BLE001
        logger.exception("stripe checkout create failed for user=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout.",
        ) from exc
    return session


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(user: AuthUser = CurrentUser) -> CheckoutResponse:
    """Start -- or resume -- a Stripe Checkout session to buy the dossier."""
    if entitlements.has_entitlement(user.id, entitlements.DOSSIER):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already own the full dossier.",
        )
    price = _price_dossier()
    if not price:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing price is not configured.",
        )
    stripe = _stripe()

    resumed = _resume_pending_checkout(stripe, user.id)
    if resumed:
        return CheckoutResponse(url=resumed)

    session = _create_session(stripe, user.id, price)
    session_id = session.get("id")
    try:
        supabase_client.record_pending_purchase(
            user_id=user.id,
            product=entitlements.DOSSIER,
            stripe_session_id=session_id,
            amount_cents=_DOSSIER_AMOUNT_CENTS,
        )
    except Exception as exc:  # noqa: BLE001
        # The session exists but nothing records who it belongs to. Expire it
        # rather than hand out a payable URL Merit cannot reconcile.
        logger.exception(
            "pending purchase write failed for user=%s session=%s", user.id, session_id
        )
        try:
            stripe.checkout.Session.expire(session_id)
        except Exception:  # noqa: BLE001
            logger.exception("could not expire orphaned stripe session=%s", session_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout. Please try again.",
        ) from exc
    return CheckoutResponse(url=session.get("url"))


@router.get("/entitlement", response_model=EntitlementResponse)
def get_entitlement(
    product: str = entitlements.DOSSIER, user: AuthUser = CurrentUser
) -> EntitlementResponse:
    """Whether the caller owns ``product``."""
    return EntitlementResponse(
        product=product, entitled=entitlements.has_entitlement(user.id, product)
    )


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

async def _raw_body(request: Request) -> bytes:
    """Read the unparsed request body for Stripe signature verification.

    The handler itself is sync -- it does blocking psycopg work and must run in
    the threadpool rather than on the event loop -- so the body is awaited here
    in a dependency and handed over as bytes.
    """
    return await request.body()


RawBody = Depends(_raw_body)


def _already_paid(session_id: str | None) -> bool:
    """True when the ledger already has this session marked paid.

    Distinguishes a duplicate Stripe delivery (expected, benign) from a paid
    session that granted nothing (an incident).
    """
    if not session_id:
        return False
    try:
        return supabase_client.purchase_status(session_id) == "paid"
    except Exception:  # noqa: BLE001
        logger.exception("purchase status lookup failed for session=%s", session_id)
        return False


def _handle_paid_session(session: dict[str, Any]) -> None:
    """Grant the dossier for a checkout session Stripe reports as paid.

    ``session`` is a plain dict normalised by _as_mapping, so every optional
    field below is allowed to be absent rather than assumed present.
    """
    session_id = session.get("id")
    payment_intent = session.get("payment_intent")
    amount = session.get("amount_total")
    metadata = _as_mapping(session.get("metadata"))
    user_id = session.get("client_reference_id") or metadata.get("user_id")
    payment_status = session.get("payment_status")

    if payment_status != "paid":
        # A dynamic payment method completes the session unpaid and settles
        # later via checkout.session.async_payment_succeeded. Nothing owed yet.
        logger.info(
            "checkout session not paid yet: session=%s payment_status=%s",
            session_id,
            payment_status,
        )
        return

    try:
        granted = supabase_client.grant_purchase(
            stripe_session_id=session_id,
            user_id=user_id,
            product=entitlements.DOSSIER,
            amount_cents=amount if isinstance(amount, int) else None,
            currency=session.get("currency") or "usd",
            stripe_payment_intent=payment_intent,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "STRIPE PAID BUT NOT GRANTED (ledger write failed): session=%s user=%s "
            "payment_intent=%s amount=%s",
            session_id,
            user_id,
            payment_intent,
            amount,
        )
        # Non-2xx so Stripe retries; a swallowed 200 here loses the grant.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not record the purchase.",
        ) from exc

    if granted:
        logger.info(
            "purchase paid: user=%s session=%s payment_intent=%s amount=%s",
            user_id,
            session_id,
            payment_intent,
            amount,
        )
        return

    if _already_paid(session_id):
        logger.info("duplicate stripe delivery for paid session=%s", session_id)
        return

    logger.error(
        "STRIPE PAID BUT NOT GRANTED: session=%s user=%s payment_intent=%s amount=%s",
        session_id,
        user_id,
        payment_intent,
        amount,
    )


@router.post("/webhook")
def stripe_webhook(
    payload: bytes = RawBody,
    stripe_signature: str = Header(default="", alias="stripe-signature"),
) -> dict:
    """Grant the entitlement when Stripe confirms a paid checkout.

    Verifies the Stripe signature so a forged request cannot grant a purchase.
    Sync on purpose: every branch below does blocking psycopg work, and on the
    event loop one slow query stalls the whole single-worker API while Stripe
    retries into it.
    """
    secret = _webhook_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook is not configured.",
        )
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, secret)
    except Exception as exc:  # noqa: BLE001 -- bad signature or malformed payload
        logger.warning("stripe webhook verification failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature."
        ) from exc

    # Normalise before reading anything. Indexing the StripeObject directly --
    # event["type"], event["data"]["object"] -- raises KeyError on any payload
    # shaped differently than expected, which on this endpoint means a 500 and
    # an ungranted charge.
    event_map = _as_mapping(event)
    event_type = event_map.get("type")
    session = _as_mapping(_as_mapping(event_map.get("data")).get("object"))

    if event_type in _PAID_EVENTS:
        _handle_paid_session(session)
    elif event_type == "checkout.session.async_payment_failed":
        logger.warning(
            "stripe async payment failed: session=%s user=%s payment_intent=%s",
            session.get("id"),
            session.get("client_reference_id"),
            session.get("payment_intent"),
        )
    return {"received": True}
