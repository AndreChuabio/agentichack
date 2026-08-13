"""Route tests for POST /publish/site and GET /publish/repos.

Auth and the BYOK key dependency are overridden so wiring and response shapes
can be asserted without a live Supabase or a real model key, matching the
posture of tests/backend/test_api.py.
"""

from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from backend.auth import AuthUser, get_current_user
from backend.byok import require_llm_key
from backend.main import app
from backend.services.market_service import Profile
from backend.services.site_service import SiteResult
from paperpilot.github_ingest import RepoSummary

USER_ID = "00000000-0000-0000-0000-000000000001"


def _profile(**overrides) -> Profile:
    fields = {"user_id": USER_ID, "github_url": "https://github.com/andre"}
    fields.update(overrides)
    return Profile(**fields)


def _summary() -> RepoSummary:
    return RepoSummary(
        full_name="andre/merit",
        html_url="https://github.com/andre/merit",
        description="evidence engine",
        language="Python",
        stars=3,
        pushed_at="2026-01-05T00:00:00",
        fork=False,
    )


def _result() -> SiteResult:
    return SiteResult(
        site_name="andre-chuabio",
        theme={"palette": "slate", "layout": "stack"},
        html_preview="<!doctype html><html></html>",
        zip_bytes=b"PK\x03\x04zip",
        skipped=[],
    )


@contextmanager
def _authed():
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=USER_ID, email="clown@example.com"
    )
    app.dependency_overrides[require_llm_key] = lambda: None
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@contextmanager
def _authed_no_key():
    """Authenticated, but with the BYOK dependency left in place.

    _authed above overrides require_llm_key, which would mask a route that
    demands an X-LLM-Key header the browser never sends. This one does not, so
    a test using it fails if BYOK creeps back onto a Merit-key surface.
    """
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=USER_ID, email="clown@example.com"
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_publish_site_returns_base64_zip():
    with _authed() as client, patch(
        "backend.routers.site.build_site", return_value=_result()
    ):
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": []}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["site_name"] == "andre-chuabio"
    assert body["zip_base64"]
    assert body["theme"]["palette"] == "slate"


def test_publish_site_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": []}
        )
    assert response.status_code == 401


def test_too_many_repos_is_rejected():
    with _authed() as client:
        response = client.post(
            "/publish/site",
            json={
                "repo_urls": [f"https://github.com/x/r{i}" for i in range(9)],
                "evidence_ids": [],
            },
        )
    assert response.status_code == 400


def test_quota_exhaustion_returns_429():
    def _over_limit(user_id, quota):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="quota spent"
        )

    with _authed() as client, patch(
        "backend.routers.site.quotas.enforce", side_effect=_over_limit
    ):
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": []}
        )
    assert response.status_code == 429


def test_evidence_ownership_403_is_not_masked_as_502():
    def _forbidden(**kwargs):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not the caller's"
        )

    with _authed() as client, patch(
        "backend.routers.site.build_site", side_effect=_forbidden
    ):
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": ["someone-else"]}
        )
    assert response.status_code == 403


def test_repos_returns_the_picker_list_and_the_saved_selection():
    with _authed() as client, patch(
        "backend.routers.site.get_profile",
        return_value=_profile(selected_repos=["andre/merit"]),
    ), patch("backend.routers.site.list_user_repos", return_value=[_summary()]):
        response = client.get("/publish/repos")
    assert response.status_code == 200
    body = response.json()
    assert body["repos"][0]["full_name"] == "andre/merit"
    assert body["repos"][0]["stars"] == 3
    assert body["selected"] == ["andre/merit"]


def test_a_profile_with_no_github_url_offers_nothing_rather_than_failing():
    """Nothing to list is an empty picker, not an error the user must clear."""
    with _authed() as client, patch(
        "backend.routers.site.get_profile", return_value=_profile(github_url="  ")
    ):
        response = client.get("/publish/repos")
    assert response.status_code == 200
    assert response.json() == {"repos": [], "selected": []}


def test_a_github_outage_is_a_502_not_a_500():
    with _authed() as client, patch(
        "backend.routers.site.get_profile", return_value=_profile()
    ), patch(
        "backend.routers.site.list_user_repos", side_effect=RuntimeError("github down")
    ):
        response = client.get("/publish/repos")
    assert response.status_code == 502


def test_repos_requires_auth():
    with TestClient(app) as client:
        assert client.get("/publish/repos").status_code == 401


def test_building_a_site_does_not_demand_a_byok_header():
    """Publish is capped by quotas.SITE and runs on Merit's key.

    It briefly required BOTH a quota and an X-LLM-Key header, which is
    contradictory -- and fatal in practice, because the web client sends that
    header on no request at all, so every build from the browser was refused
    with a 400 asking for a key the UI cannot collect.
    """
    with _authed_no_key() as client, patch(
        "backend.routers.site.build_site", return_value=_result()
    ):
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": []}
        )
    assert response.status_code == 200, response.text
