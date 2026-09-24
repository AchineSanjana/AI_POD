"""Tests for multi-tenant rate limiting, sliding window enforcement, and 429 responses."""

from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.rate_limiter import RATE_LIMITER, InMemoryRateLimiter
from src.api.recommendations import get_model_for_tenant
from src.utils.config import get_tenant_rate_limit


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Ensure global rate limiter is clean before each test."""
    RATE_LIMITER.reset()
    yield
    RATE_LIMITER.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_in_memory_rate_limiter_sliding_window():
    """Verify sliding window mechanics and Retry-After calculation."""
    limiter = InMemoryRateLimiter(window_seconds=60.0)
    now = 1000.0

    # First 3 requests should be allowed for limit=3
    r1 = limiter.check("tenant_test", scope="recommendations", custom_limit=3, now=now)
    assert r1.allowed is True
    assert r1.remaining == 2
    assert r1.retry_after == 0

    r2 = limiter.check("tenant_test", scope="recommendations", custom_limit=3, now=now + 5.0)
    assert r2.allowed is True
    assert r2.remaining == 1

    r3 = limiter.check("tenant_test", scope="recommendations", custom_limit=3, now=now + 10.0)
    assert r3.allowed is True
    assert r3.remaining == 0

    # 4th request at now + 15s exceeds limit (oldest was at now=1000.0, so retry_after = 1000 + 60 - 1015 = 45s)
    r4 = limiter.check("tenant_test", scope="recommendations", custom_limit=3, now=now + 15.0)
    assert r4.allowed is False
    assert r4.remaining == 0
    assert r4.retry_after == 45

    # After window passes oldest request (at now + 61.0s), 1 slot frees up
    r5 = limiter.check("tenant_test", scope="recommendations", custom_limit=3, now=now + 61.0)
    assert r5.allowed is True
    assert r5.remaining == 0  # 2 older requests remain in window


def test_get_tenant_rate_limit_resolution():
    """Verify rate limit parsing from config with fallback."""
    cfg = {
        "tenants": {
            "custom_tenant": {
                "rate_limit": {
                    "recommendations": 120,
                    "onboarding": 10,
                }
            },
            "integer_tenant": {
                "rate_limit": 30,
            },
            "string_tenant": {
                "rate_limit": "45/minute",
            },
            "unconfigured_tenant": {},
        }
    }

    assert get_tenant_rate_limit("custom_tenant", "recommendations", cfg) == 120
    assert get_tenant_rate_limit("custom_tenant", "onboarding", cfg) == 10
    assert get_tenant_rate_limit("integer_tenant", "recommendations", cfg) == 30
    assert get_tenant_rate_limit("string_tenant", "recommendations", cfg) == 45
    # Default fallbacks
    assert get_tenant_rate_limit("unconfigured_tenant", "recommendations", cfg) == 60
    assert get_tenant_rate_limit("unconfigured_tenant", "onboarding", cfg) == 5


def test_recommendations_rate_limit_exceeded_and_tenant_isolation(client: TestClient, monkeypatch):
    """Simulate rapid requests from Tenant A triggering 429, while Tenant B remains unaffected."""
    telco_model = get_model_for_tenant("telco_default")
    telco_cust = telco_model.customers_.iloc[0]["customer_id"]

    ecom_model = get_model_for_tenant("fixture_ecommerce")
    ecom_cust = ecom_model.customers_.iloc[0]["customer_id"]

    # Configure a small limit of 3 req/min for telco_default to test threshold quickly
    from src.utils import config as config_module
    orig_load_config = config_module.load_config

    def mock_config():
        cfg = orig_load_config()
        cfg.setdefault("tenants", {}).setdefault("telco_default", {})["rate_limit"] = {
            "recommendations": 3,
            "onboarding": 2,
        }
        return cfg

    monkeypatch.setattr("src.utils.config.load_config", mock_config)
    monkeypatch.setattr("src.api.rate_limiter.get_tenant_rate_limit", lambda t, scope="recommendations": 3 if t == "telco_default" else 60)

    # 1. Tenant A sends 3 requests within limit -> all succeed
    for i in range(3):
        resp = client.get(
            "/recommendations",
            params={"customer_id": telco_cust, "top_n": 2},
            headers={"X-API-Key": "sk-telco-xxxx"},
        )
        assert resp.status_code == 200, f"Request {i+1} should have succeeded"

    # 2. Tenant A sends 4th request -> must fail with 429 Too Many Requests
    resp_over = client.get(
        "/recommendations",
        params={"customer_id": telco_cust, "top_n": 2},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp_over.status_code == 429
    assert "Retry-After" in resp_over.headers
    retry_after = int(resp_over.headers["Retry-After"])
    assert retry_after > 0
    assert "Rate limit exceeded" in resp_over.json()["detail"]
    assert "telco_default" in resp_over.json()["detail"]

    # 3. Tenant B makes a request with their own key -> MUST BE COMPLETELY UNAFFECTED (200 OK)
    resp_b = client.get(
        f"/recommendations/{ecom_cust}",
        headers={"X-API-Key": "sk-ecommerce-xxxx"},
    )
    assert resp_b.status_code == 200
    assert resp_b.json()["tenant_id"] == "fixture_ecommerce"


def test_onboarding_strict_rate_limit(client: TestClient, monkeypatch):
    """Verify onboarding endpoints enforce separate, stricter rate limits."""
    monkeypatch.setattr(
        "src.api.rate_limiter.get_tenant_rate_limit",
        lambda t, scope="onboarding": 2 if scope == "onboarding" else 60,
    )

    # First 2 requests succeed
    for _ in range(2):
        resp = client.get(
            "/onboarding/status",
            headers={"X-API-Key": "sk-telco-xxxx"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] in ["ready", "active"]

    # 3rd request triggers 429 with Retry-After
    resp_over = client.get(
        "/onboarding/status",
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp_over.status_code == 429
    assert "Retry-After" in resp_over.headers
    assert int(resp_over.headers["Retry-After"]) > 0
    assert "onboarding" in resp_over.json()["detail"]
