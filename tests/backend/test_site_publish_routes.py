"""Route tests for the live-site endpoints.

Publishing spends no model call, so neither route takes the BYOK key
dependency: only auth is overridden here.
"""

from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth import AuthUser, get_current_user
from backend.main import app

USER_ID = "00000000-0000-0000-0000-000000000001"


@contextmanager
def _authed():
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=USER_ID, email="clown@example.com"
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_go_live_returns_the_public_url():
    with _authed() as client, patch(
        "backend.routers.site.HostedTarget.publish",
        return_value="https://meritai.me/u/andre-chuabio",
    ):
        response = client.post("/publish/site/live")
    assert response.status_code == 200
    assert response.json()["url"].endswith("/u/andre-chuabio")


def test_go_live_without_a_built_site_is_404():
    with _authed() as client, patch(
        "backend.routers.site.HostedTarget.publish",
        side_effect=ValueError("there is no built site to publish"),
    ):
        response = client.post("/publish/site/live")
    assert response.status_code == 404


def test_take_down_is_204():
    with _authed() as client, patch(
        "backend.routers.site.HostedTarget.unpublish", return_value=None
    ) as unpub:
        response = client.delete("/publish/site/live")
    assert response.status_code == 204
    unpub.assert_called_once()


def test_live_routes_require_auth():
    with TestClient(app) as client:
        assert client.post("/publish/site/live").status_code == 401
        assert client.delete("/publish/site/live").status_code == 401
