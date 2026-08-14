"""The money path: a captured charge must always become an entitlement.

Nothing covered billing.py before this file, which is the wrong place to have
no tests. Every failure pinned here is one where Stripe has the customer's $99
and Merit delivers nothing:

  - a duplicate webhook delivery granting twice (or the retry granting zero)
  - a paid session with no pending row -- a Payment Link, or a checkout whose
    ledger insert failed -- being dropped on the floor
  - a dynamic payment method settling via async_payment_succeeded, which the
    original handler ignored entirely
  - a forged webhook granting anything at all
  - a second click during webhook lag opening a second $99 session

The Stripe signature is computed for real (Stripe's t=/v1= HMAC scheme) rather
than stubbed, so construct_event actually verifies and the bad-signature test
proves the guard instead of proving a mock.

The Supabase side runs against an in-memory stand-in for the purchases table,
so grant_purchase's real branch logic executes. The fake raises on SQL it does
not recognise, so it fails loudly if the statements it mirrors ever change.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.auth import AuthUser, get_current_user
from backend.main import app
from backend.routers import billing
from paperpilot import supabase_client

USER_ID = "11111111-1111-1111-1111-111111111111"
USER = AuthUser(id=USER_ID, email="clown@example.com")
WEBHOOK_SECRET = "whsec_test_secret"
SESSION_ID = "cs_test_session"


# ---------------------------------------------------------------------------
# Stripe payload helpers
# ---------------------------------------------------------------------------

def _sign(payload: str, secret: str = WEBHOOK_SECRET) -> dict[str, str]:
    """Sign a payload the way Stripe does, so construct_event really verifies."""
    timestamp = int(time.time())
    signature = hmac.new(
        secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256
    ).hexdigest()
    return {"stripe-signature": f"t={timestamp},v1={signature}"}


def _event(
    event_type: str,
    *,
    session_id: str = SESSION_ID,
    payment_status: str = "paid",
    user_id: str | None = USER_ID,
    metadata: dict | None = None,
    amount_total: int | None = 9900,
    payment_intent: str = "pi_test_intent",
    omit: tuple[str, ...] = (),
) -> str:
    """Serialise a Stripe checkout.session event as it arrives on the wire.

    ``omit`` drops keys from the session object entirely, which is how real
    payloads arrive: optional fields are absent, not null.
    """
    session = {
        "id": session_id,
        "object": "checkout.session",
        "status": "complete",
        "payment_status": payment_status,
        "client_reference_id": user_id,
        "metadata": metadata if metadata is not None else {"user_id": user_id},
        "amount_total": amount_total,
        "currency": "usd",
        "payment_intent": payment_intent,
    }
    for key in omit:
        session.pop(key, None)
    # The top-level "object": "event" is not decoration: stripe 15's
    # construct_event reads event.object to tell v1 from v2 events and raises
    # AttributeError without it.
    return json.dumps(
        {
            "id": "evt_test",
            "object": "event",
            "type": event_type,
            "data": {"object": session},
        }
    )


# ---------------------------------------------------------------------------
# In-memory purchases table
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, rowcount: int = 0, rows: list[tuple] | None = None) -> None:
        self.rowcount = rowcount
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakePurchases:
    """Stand-in for the purchases table, dispatching on the real SQL."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        # How many times a row actually transitioned into paid. The point of
        # the idempotency tests is that this stays at 1 no matter how many
        # times Stripe delivers the same event.
        self.grants = 0

    def add_pending(self, session_id: str = SESSION_ID, **overrides) -> dict:
        row = {
            "user_id": USER_ID,
            "product": "dossier",
            "status": "pending",
            "amount_cents": 9900,
            "currency": "usd",
            "stripe_session_id": session_id,
            "stripe_payment_intent": None,
            "created_at": datetime.now(timezone.utc),
        }
        row.update(overrides)
        self.rows[session_id] = row
        return row

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        if sql.startswith("UPDATE purchases"):
            payment_intent, amount_cents, session_id = params
            row = self.rows.get(session_id)
            if row is None or row["status"] == "paid":
                return _FakeCursor(rowcount=0)
            row["status"] = "paid"
            row["stripe_payment_intent"] = payment_intent
            if amount_cents is not None:
                row["amount_cents"] = amount_cents
            self.grants += 1
            return _FakeCursor(rowcount=1)

        if sql.startswith("SELECT status FROM purchases"):
            row = self.rows.get(params[0])
            return _FakeCursor(rows=[(row["status"],)] if row else [])

        if sql.startswith("SELECT stripe_session_id FROM purchases"):
            user_id, product, since = params
            pending = [
                r
                for r in self.rows.values()
                if r["user_id"] == user_id
                and r["product"] == product
                and r["status"] == "pending"
                and r["created_at"] >= since
            ]
            pending.sort(key=lambda r: r["created_at"])
            return _FakeCursor(
                rows=[(pending[-1]["stripe_session_id"],)] if pending else []
            )

        if sql.startswith("SELECT 1 FROM purchases"):
            user_id, product = params
            owned = any(
                r["user_id"] == user_id
                and r["product"] == product
                and r["status"] == "paid"
                for r in self.rows.values()
            )
            return _FakeCursor(rows=[(1,)] if owned else [])

        if sql.startswith("INSERT INTO purchases") and "'paid'" in sql:
            user_id, product, amount, currency, session_id, intent = params
            if session_id in self.rows:  # ON CONFLICT DO NOTHING
                return _FakeCursor(rowcount=0)
            self.rows[session_id] = {
                "user_id": user_id,
                "product": product,
                "status": "paid",
                "amount_cents": amount,
                "currency": currency,
                "stripe_session_id": session_id,
                "stripe_payment_intent": intent,
                "created_at": datetime.now(timezone.utc),
            }
            self.grants += 1
            return _FakeCursor(rowcount=1)

        if sql.startswith("INSERT INTO purchases") and "'pending'" in sql:
            user_id, product, amount, currency, session_id = params
            if session_id in self.rows:
                return _FakeCursor(rowcount=0)
            self.rows[session_id] = {
                "user_id": user_id,
                "product": product,
                "status": "pending",
                "amount_cents": amount,
                "currency": currency,
                "stripe_session_id": session_id,
                "stripe_payment_intent": None,
                "created_at": datetime.now(timezone.utc),
            }
            return _FakeCursor(rowcount=1)

        raise AssertionError(f"unexpected SQL against purchases: {sql}")

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Stripe API test double (checkout only; the webhook uses the real module)
# ---------------------------------------------------------------------------

class _FakeSessionAPI:
    def __init__(self, retrieved: dict | None = None) -> None:
        self.created: list[dict] = []
        self.expired: list[str] = []
        self.retrieved = retrieved

    def create(self, **kwargs) -> dict:
        self.created.append(kwargs)
        return {
            "id": f"cs_new_{len(self.created)}",
            "url": "https://checkout.stripe.com/c/pay/new",
            "status": "open",
        }

    def retrieve(self, session_id: str) -> dict:
        if self.retrieved is None:
            raise RuntimeError(f"no such session: {session_id}")
        return self.retrieved

    def expire(self, session_id: str) -> None:
        self.expired.append(session_id)


class _FakeStripe:
    def __init__(self, sessions: _FakeSessionAPI) -> None:
        self.checkout = type("_Checkout", (), {"Session": sessions})()


@pytest.fixture
def db(monkeypatch) -> _FakePurchases:
    fake = _FakePurchases()
    monkeypatch.setattr(supabase_client, "get_conn", lambda: fake)
    return fake


@pytest.fixture
def stripe_env(monkeypatch) -> None:
    """Billing configured. Read at call time, so setenv is enough."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_PRICE_DOSSIER", "price_test_dossier")
    monkeypatch.setenv("FRONTEND_URL", "https://merit.test")


def _post_webhook(payload: str, headers: dict[str, str] | None = None):
    with TestClient(app) as client:
        return client.post(
            "/billing/webhook",
            content=payload,
            headers=headers if headers is not None else _sign(payload),
        )


# ---------------------------------------------------------------------------
# Webhook: idempotency
# ---------------------------------------------------------------------------

def test_double_delivery_of_the_same_event_grants_exactly_once(stripe_env, db):
    """Stripe retries. Two identical deliveries must both 200 and grant once."""
    db.add_pending(amount_cents=9900)
    payload = _event("checkout.session.completed", amount_total=12345)

    first = _post_webhook(payload)
    second = _post_webhook(payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert db.rows[SESSION_ID]["status"] == "paid"
    assert db.grants == 1, "a duplicate delivery must not grant a second time"
    assert db.rows[SESSION_ID]["stripe_payment_intent"] == "pi_test_intent"
    # M4: the ledger records what Stripe actually captured, not the hardcoded
    # 9900 the pending row was seeded with.
    assert db.rows[SESSION_ID]["amount_cents"] == 12345


def test_duplicate_delivery_is_not_logged_as_an_incident(stripe_env, db, caplog):
    db.add_pending()
    payload = _event("checkout.session.completed")

    _post_webhook(payload)
    with caplog.at_level(logging.INFO):
        second = _post_webhook(payload)

    assert second.status_code == 200
    assert "STRIPE PAID BUT NOT GRANTED" not in caplog.text


# ---------------------------------------------------------------------------
# Webhook: no pending row (Payment Link, or a failed pending insert)
# ---------------------------------------------------------------------------

def test_paid_session_with_no_pending_row_grants_via_client_reference_id(
    stripe_env, db
):
    """No row exists, so the webhook inserts the paid row itself."""
    assert db.rows == {}
    payload = _event("checkout.session.completed", amount_total=9900)

    resp = _post_webhook(payload)

    assert resp.status_code == 200
    assert db.grants == 1
    row = db.rows[SESSION_ID]
    assert row["status"] == "paid"
    assert row["user_id"] == USER_ID
    assert row["product"] == "dossier"
    assert row["amount_cents"] == 9900


def test_paid_session_falls_back_to_metadata_user_id(stripe_env, db):
    """client_reference_id absent but metadata carries the user: still grants."""
    payload = _event(
        "checkout.session.completed", user_id=None, metadata={"user_id": USER_ID}
    )

    resp = _post_webhook(payload)

    assert resp.status_code == 200
    assert db.rows[SESSION_ID]["user_id"] == USER_ID


def test_unattributable_paid_session_is_logged_loudly(stripe_env, db, caplog):
    """Money captured with no way to know whose it is must not be silent."""
    payload = _event("checkout.session.completed", user_id=None, metadata={})

    with caplog.at_level(logging.ERROR):
        resp = _post_webhook(payload)

    assert resp.status_code == 200, "Stripe must not be made to retry forever"
    assert db.grants == 0
    assert "STRIPE PAID BUT NOT GRANTED" in caplog.text
    assert SESSION_ID in caplog.text
    assert "pi_test_intent" in caplog.text


# ---------------------------------------------------------------------------
# Webhook: asynchronous settlement
# ---------------------------------------------------------------------------

def test_async_payment_succeeded_grants(stripe_env, db):
    """The event the original handler ignored while the charge was captured."""
    db.add_pending()
    payload = _event("checkout.session.async_payment_succeeded")

    resp = _post_webhook(payload)

    assert resp.status_code == 200
    assert db.rows[SESSION_ID]["status"] == "paid"
    assert db.grants == 1


def test_unpaid_completion_waits_for_the_async_event(stripe_env, db):
    """A session that completes unpaid grants nothing until it settles."""
    db.add_pending()

    unpaid = _post_webhook(
        _event("checkout.session.completed", payment_status="unpaid")
    )
    assert unpaid.status_code == 200
    assert db.rows[SESSION_ID]["status"] == "pending"
    assert db.grants == 0

    settled = _post_webhook(_event("checkout.session.async_payment_succeeded"))
    assert settled.status_code == 200
    assert db.rows[SESSION_ID]["status"] == "paid"
    assert db.grants == 1


def test_async_payment_failed_is_logged_and_grants_nothing(stripe_env, db, caplog):
    db.add_pending()
    payload = _event(
        "checkout.session.async_payment_failed", payment_status="unpaid"
    )

    with caplog.at_level(logging.WARNING):
        resp = _post_webhook(payload)

    assert resp.status_code == 200
    assert db.grants == 0
    assert "async payment failed" in caplog.text


# ---------------------------------------------------------------------------
# Webhook: hostile and unknown input
# ---------------------------------------------------------------------------

def test_bad_signature_returns_400_and_grants_nothing(stripe_env, db):
    """A forged webhook is the cheapest way to steal a $99 product."""
    db.add_pending()
    payload = _event("checkout.session.completed")

    resp = _post_webhook(payload, headers={"stripe-signature": "t=1,v1=deadbeef"})

    assert resp.status_code == 400
    assert db.grants == 0
    assert db.rows[SESSION_ID]["status"] == "pending"


def test_payload_signed_with_the_wrong_secret_is_rejected(stripe_env, db):
    db.add_pending()
    payload = _event("checkout.session.completed")

    resp = _post_webhook(payload, headers=_sign(payload, secret="whsec_attacker"))

    assert resp.status_code == 400
    assert db.grants == 0


def test_unknown_event_type_returns_200_without_crashing(stripe_env, db):
    """Stripe sends whatever the account is subscribed to; ignore it calmly."""
    payload = json.dumps(
        {
            "id": "evt_x",
            "object": "event",
            "type": "payment_intent.created",
            "data": {"object": {}},
        }
    )

    resp = _post_webhook(payload)

    assert resp.status_code == 200
    assert resp.json() == {"received": True}
    assert db.grants == 0


def test_webhook_503s_when_the_signing_secret_is_unset(monkeypatch, db):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    payload = _event("checkout.session.completed")

    resp = _post_webhook(payload)

    assert resp.status_code == 503
    assert db.grants == 0


# ---------------------------------------------------------------------------
# The StripeObject access class that took a real payment in production.
#
# A live test-mode purchase (event evt_1U49vfDmBmHFG2yZSC7OawDS) was captured
# and never granted: the deployed handler read session.get("payment_status"),
# which raises AttributeError on stripe-python 15, so the endpoint 500'd and
# Stripe retried into the same wall. Every webhook test in this file drives
# real construct_event output rather than a hand-built dict, which is the only
# reason that class of bug is visible here at all -- a plain-dict mock passes
# while production burns.
# ---------------------------------------------------------------------------


def test_stripe_objects_are_hostile_to_every_naive_access_style():
    """Documents why _as_mapping exists, in the SDK's own behaviour."""
    from stripe._stripe_object import StripeObject

    obj = StripeObject.construct_from({"payment_status": "paid"}, None)

    assert not isinstance(obj, dict), "15.x dropped the dict base class"
    assert not hasattr(obj, "get"), "so .get() is gone with it"
    with pytest.raises(AttributeError):
        obj.payment_intent  # absent optional field, attribute style
    with pytest.raises(KeyError):
        obj["payment_intent"]  # absent optional field, index style

    # to_dict_recursive() is NOT the escape hatch it looks like: on 15.x the
    # public name does not exist and reaching for it raises the very error
    # being guarded against.
    with pytest.raises(AttributeError):
        obj.to_dict_recursive()


def test_as_mapping_normalises_every_payload_shape():
    from stripe._stripe_object import StripeObject

    obj = StripeObject.construct_from({"payment_status": "paid"}, None)
    mapped = billing._as_mapping(obj)

    assert isinstance(mapped, dict)
    assert mapped.get("payment_status") == "paid"
    assert mapped.get("payment_intent") is None, "absent optional key is None"
    # Plain dicts (Payment Link payloads, test doubles) pass straight through,
    # and a missing node normalises to an empty mapping rather than None.
    assert billing._as_mapping({"a": 1}).get("a") == 1
    assert billing._as_mapping(None) == {}
    assert billing._as_mapping("not a payload") == {}


def test_a_session_reaching_the_handler_is_a_real_stripe_object(stripe_env, db):
    """Guards the fixtures themselves: these tests must not drift to dicts."""
    seen: list = []
    payload = _event("checkout.session.completed")

    import stripe

    original = stripe.Webhook.construct_event

    def spy(*args, **kwargs):
        event = original(*args, **kwargs)
        seen.append(event)
        return event

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stripe.Webhook, "construct_event", spy)
        resp = _post_webhook(payload)

    assert resp.status_code == 200
    assert seen, "construct_event was never reached"
    event = seen[0]
    assert type(event).__name__ == "Event"
    assert not isinstance(event, dict), (
        "the event handed to the handler must be a real StripeObject; a plain "
        "dict fixture would pass while production 500s"
    )


def test_handler_accepts_a_directly_constructed_stripe_event(stripe_env, db, monkeypatch):
    """The same payload built as a StripeObject, bypassing signature checks."""
    import stripe

    db.add_pending()
    payload_dict = json.loads(_event("checkout.session.completed"))
    event_object = stripe.Event.construct_from(payload_dict, None)
    assert not isinstance(event_object, dict)

    monkeypatch.setattr(
        stripe.Webhook, "construct_event", lambda *a, **k: event_object
    )

    resp = _post_webhook("{}", headers={"stripe-signature": "unused"})

    assert resp.status_code == 200
    assert db.rows[SESSION_ID]["status"] == "paid"
    assert db.grants == 1


def test_a_full_fidelity_live_payload_grants(stripe_env, db):
    """The shape Stripe actually sends, not the seven fields we happen to read.

    Modelled on the live test-mode event that was captured and never granted,
    including the nested objects and null-valued optional fields a real
    checkout.session.completed carries. The handler must pick the four fields
    it needs out of this without tripping over any of the rest.
    """
    db.add_pending(session_id="cs_test_a1etJJUjSbqyhvoYoYmLI0Iw")
    session = {
        "id": "cs_test_a1etJJUjSbqyhvoYoYmLI0Iw",
        "object": "checkout.session",
        "adaptive_pricing": {"enabled": False},
        "after_expiration": None,
        "allow_promotion_codes": None,
        "amount_subtotal": 9900,
        "amount_total": 9900,
        "automatic_tax": {"enabled": False, "liability": None, "status": None},
        "billing_address_collection": None,
        "cancel_url": "https://merit.test/track?checkout=cancelled",
        "client_reference_id": USER_ID,
        "client_secret": None,
        "consent": None,
        "consent_collection": None,
        "created": 1786000000,
        "currency": "usd",
        "custom_fields": [],
        "custom_text": {"submit": None, "terms_of_service_acceptance": None},
        "customer": "cus_TestCustomer",
        "customer_details": {
            "address": {"country": "US", "postal_code": "94107"},
            "email": "clown@example.com",
            "name": "Senor Clown",
            "tax_exempt": "none",
            "tax_ids": [],
        },
        "customer_email": None,
        "expires_at": 1786086400,
        "invoice": None,
        "livemode": False,
        "locale": None,
        "metadata": {"user_id": USER_ID, "product": "dossier"},
        "mode": "payment",
        "payment_intent": "pi_3TestPaymentIntent",
        "payment_method_types": ["card"],
        "payment_status": "paid",
        "recovered_from": None,
        "status": "complete",
        "success_url": "https://merit.test/track?purchased=dossier",
        "total_details": {"amount_discount": 0, "amount_shipping": 0, "amount_tax": 0},
        "ui_mode": "hosted",
    }
    payload = json.dumps(
        {
            "id": "evt_1U49vfDmBmHFG2yZSC7OawDS",
            "object": "event",
            "api_version": "2026-06-30.basil",
            "created": 1786000001,
            "livemode": False,
            "pending_webhooks": 1,
            "request": {"id": None, "idempotency_key": None},
            "type": "checkout.session.completed",
            "data": {"object": session},
        }
    )

    resp = _post_webhook(payload)

    assert resp.status_code == 200
    row = db.rows["cs_test_a1etJJUjSbqyhvoYoYmLI0Iw"]
    assert row["status"] == "paid"
    assert row["stripe_payment_intent"] == "pi_3TestPaymentIntent"
    assert row["amount_cents"] == 9900
    assert db.grants == 1

    # The retry Stripe is still holding must land as a no-op, not a re-grant.
    assert _post_webhook(payload).status_code == 200
    assert db.grants == 1


def test_absent_optional_keys_still_grant_against_the_pending_row(stripe_env, db):
    """payment_intent, client_reference_id, metadata, amount_total all missing.

    Real payloads omit optional fields rather than sending null. The pending
    row already knows whose money this is, so the grant must still land.
    """
    db.add_pending(amount_cents=9900)
    payload = _event(
        "checkout.session.completed",
        omit=("payment_intent", "client_reference_id", "metadata", "amount_total"),
    )

    resp = _post_webhook(payload)

    assert resp.status_code == 200
    assert db.grants == 1
    row = db.rows[SESSION_ID]
    assert row["status"] == "paid"
    assert row["stripe_payment_intent"] is None
    # No amount on the event means COALESCE keeps what the ledger already had.
    assert row["amount_cents"] == 9900


def test_absent_optional_keys_with_no_row_are_logged_not_crashed(
    stripe_env, db, caplog
):
    """Nothing to grant against and nothing to attribute it to: log, do not 500."""
    payload = _event(
        "checkout.session.completed",
        omit=("payment_intent", "client_reference_id", "metadata", "amount_total"),
    )

    with caplog.at_level(logging.ERROR):
        resp = _post_webhook(payload)

    assert resp.status_code == 200
    assert db.grants == 0
    assert "STRIPE PAID BUT NOT GRANTED" in caplog.text


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def _as_user() -> None:
    app.dependency_overrides[get_current_user] = lambda: USER


def test_checkout_resumes_the_existing_pending_session(stripe_env, db, monkeypatch):
    """A second click during webhook lag must not open a second $99 session."""
    db.add_pending(session_id="cs_in_flight")
    sessions = _FakeSessionAPI(
        retrieved={
            "id": "cs_in_flight",
            "status": "open",
            "url": "https://checkout.stripe.com/c/pay/in_flight",
        }
    )
    monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe(sessions))

    _as_user()
    try:
        with TestClient(app) as client:
            resp = client.post("/billing/checkout")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["url"] == "https://checkout.stripe.com/c/pay/in_flight"
    assert sessions.created == [], "a second checkout session was created"


def test_checkout_409s_while_a_completed_session_is_still_being_confirmed(
    stripe_env, db, monkeypatch
):
    """Money is already captured; the grant is only lagging. Do not charge again."""
    db.add_pending(session_id="cs_paying")
    sessions = _FakeSessionAPI(
        retrieved={"id": "cs_paying", "status": "complete", "url": None}
    )
    monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe(sessions))

    _as_user()
    try:
        with TestClient(app) as client:
            resp = client.post("/billing/checkout")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert sessions.created == []


def test_checkout_creates_a_card_only_idempotent_session(stripe_env, db, monkeypatch):
    """Card only, because dynamic methods settle asynchronously."""
    sessions = _FakeSessionAPI()
    monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe(sessions))

    _as_user()
    try:
        with TestClient(app) as client:
            resp = client.post("/billing/checkout")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert len(sessions.created) == 1
    created = sessions.created[0]
    assert created["payment_method_types"] == ["card"]
    assert created["client_reference_id"] == USER_ID
    assert created["idempotency_key"].startswith(f"dossier-{USER_ID}-")
    # The pending row is what links this session back to a user.
    assert db.rows["cs_new_1"]["status"] == "pending"


def test_checkout_expires_the_session_when_the_ledger_write_fails(
    stripe_env, db, monkeypatch
):
    """No orphan payable URL: a session Merit cannot reconcile gets expired."""
    sessions = _FakeSessionAPI()
    monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe(sessions))

    def boom(**kwargs):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(supabase_client, "record_pending_purchase", boom)

    _as_user()
    try:
        with TestClient(app) as client:
            resp = client.post("/billing/checkout")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 502
    assert sessions.expired == ["cs_new_1"]


def test_checkout_refuses_when_the_caller_already_owns_the_dossier(
    stripe_env, db, monkeypatch
):
    db.add_pending(session_id="cs_paid", status="paid")
    sessions = _FakeSessionAPI()
    monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe(sessions))

    _as_user()
    try:
        with TestClient(app) as client:
            resp = client.post("/billing/checkout")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert sessions.created == []


def test_stale_pending_session_does_not_block_a_new_checkout(
    stripe_env, db, monkeypatch
):
    """Outside the reuse window, an abandoned session is not resumed."""
    db.add_pending(
        session_id="cs_abandoned",
        created_at=datetime.now(timezone.utc) - timedelta(hours=6),
    )
    sessions = _FakeSessionAPI()
    monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe(sessions))

    _as_user()
    try:
        with TestClient(app) as client:
            resp = client.post("/billing/checkout")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert len(sessions.created) == 1
