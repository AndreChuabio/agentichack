"""Entitlements: does a user own a paid product?

Purchases are granted only by the Stripe webhook (server-side, service role), so
this is a read-only check the paid surfaces gate on.
"""

from __future__ import annotations

import os

from paperpilot import supabase_client

# Product keys. Keep in sync with the Stripe products and the purchases.product column.
DOSSIER = "dossier"


def billing_enabled() -> bool:
    """True when a Stripe price is configured -- i.e. the paywall is active.

    When unset the dossier stays free, so the paywall can ship dark and be
    switched on later just by setting the Stripe env vars. No redeploy of a
    different code path is needed.
    """
    return bool(os.environ.get("STRIPE_PRICE_DOSSIER"))


def has_entitlement(user_id: str, product: str) -> bool:
    """True when the user may access ``product``.

    Free (True) whenever billing is disabled; otherwise requires a paid purchase.
    """
    if not billing_enabled():
        return True
    return supabase_client.has_paid_product(user_id, product)
