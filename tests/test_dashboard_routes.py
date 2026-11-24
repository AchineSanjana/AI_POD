"""Tests for dashboard route separation and SPA routing.

Verifies:
1. Versioned API routes /v1/dashboard/* exist and require authentication (401 without auth).
2. SPA routes /dashboard and /dashboard/catalog return HTML (dist/index.html when present or fallback HTML).
3. No unversioned /dashboard/* routes collide or shadow the SPA routes.
"""
import pytest
from fastapi.testclient import TestClient
from src.api.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_v1_dashboard_endpoints_require_auth(client):
    """Verify versioned /v1/dashboard/* endpoints are intact and reject unauthenticated requests."""
    endpoints = [
        "/v1/dashboard/overview",
        "/v1/dashboard/models",
        "/v1/dashboard/analytics",
        "/v1/dashboard/events",
    ]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 401, f"Expected 401 Unauthorized for {ep}, got {resp.status_code}"
        data = resp.json()
        assert "detail" in data, f"Expected error detail in {ep} response"


def test_spa_dashboard_routes_serve_html(client):
    """Verify /dashboard and /dashboard/catalog return 200 HTML for SPA navigation."""
    spa_routes = [
        "/dashboard",
        "/dashboard/catalog",
        "/dashboard/keys",
        "/dashboard/model",
        "/dashboard/analytics",
        "/dashboard/settings",
    ]
    for route in spa_routes:
        resp = client.get(route)
        assert resp.status_code == 200, f"Expected 200 OK for SPA route {route}, got {resp.status_code}"
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type, f"Expected text/html content-type for {route}, got {content_type}"
        text = resp.text
        # Must contain HTML root element or doctype
        assert "<html" in text.lower() or "<!doctype" in text.lower() or "root" in text, (
            f"Expected HTML content for {route}"
        )


def test_unversioned_dashboard_does_not_return_api_401(client):
    """Verify /dashboard/overview is handled by SPA HTML routing rather than returning 401 JSON API response."""
    resp = client.get("/dashboard/overview")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
