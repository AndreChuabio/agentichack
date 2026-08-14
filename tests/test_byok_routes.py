"""Pins which routes demand the caller's own key and which fall back to Merit's.

The line is cost, not convenience. Reading a repo is input-token dominated --
github_ingest caps a bundle at 600K tokens -- so a surge of users on Merit's key
is a bill with no natural ceiling, and those two routes keep RequireLLMKey.
Drafting an email, drafting a section and embedding a summary are all bounded at
a few hundred output tokens, so Merit absorbs them (capped by quotas.admit) and
the product works on first visit rather than 400ing at a key field that does not
exist in the UI.

Both halves are pinned, because either drifting is a real failure: a repo read
falling back to Merit's key is an uncapped bill, and a cheap route demanding a
key is a dead button.
"""

from fastapi.testclient import TestClient

from backend.auth import AuthUser, get_current_user
from backend.main import app

_USER = AuthUser(id="00000000-0000-0000-0000-000000000001", email="clown@example.com")

_RESEARCH_SUMMARY = {
    "problem": "p",
    "contribution": "c",
    "method": "m",
    "results": "r",
    "limitations": "l",
}

# Expensive: a 600K-token repo bundle per call. These must keep rejecting.
_BYOK_ROUTES = [
    ("POST", "/ingest", {"repo_url": "https://github.com/octocat/hello"}),
    ("POST", "/extract-plugin", {"repo_url": "https://github.com/octocat/hello"}),
]

# Cheap: output-bounded at a few hundred tokens. These must NOT reject, or the
# button is unreachable from a web client that sends no key header.
_FALLBACK_ROUTES = [
    ("POST", "/draft", {"summary": _RESEARCH_SUMMARY, "venue": {"name": "ICML"}}),
    ("POST", "/match", {"summary": _RESEARCH_SUMMARY}),
    ("POST", "/market/outreach/generate", {"purpose": "CAREER", "context": "ctx"}),
]


def test_expensive_routes_still_reject_a_missing_key():
    """The repo-reading routes 400 without an X-LLM-Key header."""
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        with TestClient(app) as client:
            for method, path, body in _BYOK_ROUTES:
                resp = client.request(method, path, json=body)
                assert resp.status_code == 400, (
                    f"{method} {path} returned {resp.status_code}, expected 400 "
                    "without X-LLM-Key"
                )
                assert "X-LLM-Key" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_cheap_routes_do_not_demand_a_key():
    """The output-bounded routes must not 400 for a missing key.

    The web client sends X-LLM-Key on no request and no screen collects one, so
    a 400 here is a permanently dead button rather than a prompt to supply
    something.
    """
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        with TestClient(app) as client:
            for method, path, body in _FALLBACK_ROUTES:
                resp = client.request(method, path, json=body)
                assert resp.status_code != 400 or "X-LLM-Key" not in resp.text, (
                    f"{method} {path} refused for a missing key; it runs on "
                    "Merit's key and is capped instead"
                )
    finally:
        app.dependency_overrides.clear()


def test_track_route_does_not_require_llm_key(monkeypatch):
    """A Track route (evidence ledger) must not 400 for a missing X-LLM-Key."""
    from backend.routers import evidence as evidence_router

    monkeypatch.setattr(
        evidence_router.evidence_service, "evidence_by_criterion", lambda user_id: {}
    )
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        with TestClient(app) as client:
            resp = client.get("/evidence")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code != 400
