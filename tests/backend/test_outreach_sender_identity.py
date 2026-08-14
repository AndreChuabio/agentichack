"""Drafts are written as the authed caller, not as the Senso workspace owner.

Regression tests for a live cross-user PII leak: a brand-new user's drafts
came back written as another person because the pipeline never read the
caller's saved user_profile and let Senso knowledge-base content supply the
sender identity. These tests pin that the generate route loads the caller's
profile and threads it end to end, and that two different users produce two
different senders.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.auth import AuthUser, get_current_user
from backend.main import app
from backend.services import market_service
from paperpilot.outreach.orchestrator import DraftCard

USER_A = "00000000-0000-0000-0000-00000000000a"
USER_B = "00000000-0000-0000-0000-00000000000b"

_PROFILES = {
    USER_A: market_service.Profile(user_id=USER_A, name="QA Tester", title="QA Engineer"),
    USER_B: market_service.Profile(user_id=USER_B, name="Other Person", title="Designer"),
}


class _NoopConn:
    """Connection stand-in for paths that only need close()."""

    def close(self) -> None:
        pass


def test_service_loads_caller_profile_when_not_supplied(monkeypatch):
    """generate_outreach self-loads the caller's profile as the sender."""
    monkeypatch.delenv("SENSO_API_KEY", raising=False)
    monkeypatch.setattr(
        market_service, "get_profile", lambda user_id, conn=None: _PROFILES[user_id]
    )
    monkeypatch.setattr(
        market_service.supabase_client, "get_conn", lambda: _NoopConn()
    )
    captured: dict = {}

    def fake_generate_drafts(**kwargs):
        captured.update(kwargs)
        return [
            DraftCard(
                channel="linkedin_dm",
                content_type_id="",
                sample_job_id="",
                markdown="drafted",
            )
        ]

    monkeypatch.setattr(market_service, "generate_drafts", fake_generate_drafts)

    cards = market_service.generate_outreach(
        user_id=USER_A, purpose="CAREER", context="ctx"
    )

    assert cards[0]["markdown"] == "drafted"
    sender = captured["sender_profile"]
    assert sender["name"] == "QA Tester"
    assert "user_id" not in sender


def _post_generate(user_id: str, monkeypatch) -> dict:
    """POST /market/outreach/generate as user_id; return the captured kwargs."""
    from backend import quotas

    monkeypatch.setattr(quotas, "admit", lambda uid, quota: None)
    monkeypatch.setattr(
        market_service, "get_profile", lambda uid, conn=None: _PROFILES[uid]
    )
    captured: dict = {}

    def fake_generate_outreach(**kwargs):
        captured.update(kwargs)
        return [
            {
                "channel": "linkedin_dm",
                "content_type_id": "",
                "sample_job_id": "",
                "markdown": "ok",
                "draft_id": "",
                "error": None,
            }
        ]

    monkeypatch.setattr(market_service, "generate_outreach", fake_generate_outreach)

    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=user_id, email="user@example.com"
    )
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/market/outreach/generate",
                json={"purpose": "CAREER", "context": "ctx"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    return captured


def test_route_threads_the_callers_profile_as_sender(monkeypatch):
    """The generate route loads the caller's profile and passes it through."""
    captured = _post_generate(USER_A, monkeypatch)
    assert captured["user_id"] == USER_A
    assert captured["sender_profile"]["name"] == "QA Tester"
    assert "user_id" not in captured["sender_profile"]


def test_a_different_user_yields_a_different_sender(monkeypatch):
    """Two authed users get their own identities, never each other's."""
    captured_a = _post_generate(USER_A, monkeypatch)
    captured_b = _post_generate(USER_B, monkeypatch)
    assert captured_a["sender_profile"]["name"] == "QA Tester"
    assert captured_b["sender_profile"]["name"] == "Other Person"
    assert captured_a["sender_profile"] != captured_b["sender_profile"]
