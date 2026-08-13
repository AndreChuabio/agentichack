"""Entitlements: does a user own a paid product?

Purchases are granted only by the Stripe webhook (server-side, service role), so
this is a read-only check the paid surfaces gate on.
"""

from __future__ import annotations

import os

from paperpilot import supabase_client

# Product keys. Keep in sync with the Stripe products and the purchases.product column.
DOSSIER = "dossier"
PORTFOLIO = "portfolio"


def _price_env(product: str) -> str:
    """The env var naming this product's Stripe price."""
    return f"STRIPE_PRICE_{product.upper()}"


def billing_enabled(product: str = DOSSIER) -> bool:
    """True when a Stripe price is configured for ``product``.

    When unset that product stays free, so a paywall can ship dark and be
    switched on later just by setting the env var. No redeploy of a different
    code path is needed. Per-product rather than global so a second product can
    ship dark while the first is already charging; the default keeps every
    existing dossier call site unchanged.
    """
    return bool(os.environ.get(_price_env(product)))


def has_entitlement(user_id: str, product: str) -> bool:
    """True when the user may access ``product``.

    Free (True) whenever billing is disabled for that product; otherwise
    requires a paid purchase.
    """
    if not billing_enabled(product):
        return True
    return supabase_client.has_paid_product(user_id, product)
