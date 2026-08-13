"""Route tests for POST /publish/site.

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
from backend.services.site_service import SiteResult

USER_ID = "00000000-0000-0000-0000-000000000001"


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
