import backend.entitlements as ent
from backend import quotas


def test_dossier_billing_still_reads_its_own_env(monkeypatch):
    monkeypatch.delenv("STRIPE_PRICE_DOSSIER", raising=False)
    assert ent.billing_enabled() is False
    monkeypatch.setenv("STRIPE_PRICE_DOSSIER", "price_123")
    assert ent.billing_enabled() is True


def test_portfolio_bills_independently_of_dossier(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_DOSSIER", "price_123")
    monkeypatch.delenv("STRIPE_PRICE_PORTFOLIO", raising=False)
    assert ent.billing_enabled(ent.PORTFOLIO) is False


def test_portfolio_is_free_while_its_price_is_unset(monkeypatch):
    monkeypatch.delenv("STRIPE_PRICE_PORTFOLIO", raising=False)
    assert ent.has_entitlement("any-user-id", ent.PORTFOLIO) is True


def test_site_quota_is_five_per_thirty_days():
    assert quotas.SITE.limit == 5
    assert quotas.SITE.window_days == 30
    assert quotas.SITE.kind_prefix == "site_build"
