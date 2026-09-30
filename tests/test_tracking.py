"""Tests for POST /v1/track endpoint.

Verifies:
- Public-key-only authentication.
- Payload shape validation (rejecting malformed events with 400).
- Tenant resolution from public key (ignoring body).
- Step 19 queue stub pushing and queue contents.
- Fast minimal 202 Accepted response.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.tracking import clear_queue, get_queued_events


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_queue():
    """Ensure clean queue before and after every test."""
    clear_queue()
    yield
    clear_queue()


def test_track_valid_events(client: TestClient):
    """Test sending multiple valid events and verifying 202 response and queue contents."""
    public_key = "pk-telco-xxxx"

    # 1. Valid view event (anonymous customer_id = null)
    view_payload = {
        "event_type": "view",
        "customer_id": None,
        "session_id": "sess_browser_001",
        "product_id": "prod_phone_service",
    }
    resp1 = client.post("/v1/track", json=view_payload, headers={"X-API-Key": public_key})
    assert resp1.status_code == 202
    assert resp1.json() == {"status": "accepted"}

    # 2. Valid add_to_cart event with quantity and customer_id
    cart_payload = {
        "event_type": "add_to_cart",
        "customer_id": "cust_alice_123",
        "session_id": "sess_browser_001",
        "product_id": "prod_dsl_internet",
        "quantity": 2,
    }
    resp2 = client.post("/v1/track", json=cart_payload, headers={"X-API-Key": public_key})
    assert resp2.status_code == 202
    assert resp2.json() == {"status": "accepted"}

    # 3. Valid purchase event with explicit ISO-8601 timestamp
    purchase_payload = {
        "event_type": "purchase",
        "customer_id": "cust_alice_123",
        "session_id": "sess_browser_001",
        "product_id": "prod_dsl_internet",
        "quantity": 1,
        "timestamp": "2026-09-30T12:00:00Z",
    }
    resp3 = client.post("/v1/track", json=purchase_payload, headers={"X-API-Key": public_key})
    assert resp3.status_code == 202
    assert resp3.json() == {"status": "accepted"}

    # Verify queue contents
    queued = get_queued_events()
    assert len(queued) == 3

    # Check view event in queue
    ev1 = queued[0]
    assert ev1["tenant_id"] == "telco_default"
    assert ev1["event_type"] == "view"
    assert ev1["customer_id"] is None
    assert ev1["session_id"] == "sess_browser_001"
    assert ev1["product_id"] == "prod_phone_service"
    assert ev1["quantity"] is None
    assert isinstance(ev1["timestamp"], str)
    assert len(ev1["timestamp"]) > 0

    # Check add_to_cart event in queue
    ev2 = queued[1]
    assert ev2["tenant_id"] == "telco_default"
    assert ev2["event_type"] == "add_to_cart"
    assert ev2["customer_id"] == "cust_alice_123"
    assert ev2["session_id"] == "sess_browser_001"
    assert ev2["product_id"] == "prod_dsl_internet"
    assert ev2["quantity"] == 2

    # Check purchase event in queue
    ev3 = queued[2]
    assert ev3["tenant_id"] == "telco_default"
    assert ev3["event_type"] == "purchase"
    assert ev3["customer_id"] == "cust_alice_123"
    assert ev3["timestamp"] == "2026-09-30T12:00:00Z"


def test_track_tenant_resolved_strictly_from_public_key(client: TestClient):
    """Confirm tenant is resolved strictly from public key and request body tenant_id is ignored."""
    public_key = "pk-telco-xxxx"

    payload = {
        "event_type": "view",
        "customer_id": "cust_1",
        "session_id": "sess_1",
        "product_id": "prod_1",
        "tenant_id": "malicious_spoofed_tenant",
    }
    resp = client.post("/v1/track", json=payload, headers={"X-API-Key": public_key})
    assert resp.status_code == 202

    queued = get_queued_events()
    assert len(queued) == 1
    assert queued[0]["tenant_id"] == "telco_default"


def test_track_rejects_malformed_events_with_400(client: TestClient):
    """Confirm malformed payloads return 400 Bad Request and are not added to the queue."""
    public_key = "pk-telco-xxxx"

    # Base valid payload
    base = {
        "event_type": "view",
        "session_id": "sess_valid",
        "product_id": "prod_valid",
    }

    # 1. Invalid event_type
    resp = client.post(
        "/v1/track",
        json={**base, "event_type": "invalid_type"},
        headers={"X-API-Key": public_key},
    )
    assert resp.status_code == 400
    assert "Invalid 'event_type'" in resp.json()["detail"]

    # 2. Missing session_id
    resp = client.post(
        "/v1/track",
        json={"event_type": "view", "product_id": "prod_valid"},
        headers={"X-API-Key": public_key},
    )
    assert resp.status_code == 400
    assert "session_id" in resp.json()["detail"]

    # 3. Empty/whitespace session_id
    resp = client.post(
        "/v1/track",
        json={**base, "session_id": "   "},
        headers={"X-API-Key": public_key},
    )
    assert resp.status_code == 400
    assert "session_id" in resp.json()["detail"]

    # 4. Missing product_id
    resp = client.post(
        "/v1/track",
        json={"event_type": "view", "session_id": "sess_valid"},
        headers={"X-API-Key": public_key},
    )
    assert resp.status_code == 400
    assert "product_id" in resp.json()["detail"]

    # 5. Non-numeric quantity
    resp = client.post(
        "/v1/track",
        json={**base, "quantity": "three"},
        headers={"X-API-Key": public_key},
    )
    assert resp.status_code == 400
    assert "quantity" in resp.json()["detail"]

    # 6. Negative quantity
    resp = client.post(
        "/v1/track",
        json={**base, "quantity": -5},
        headers={"X-API-Key": public_key},
    )
    assert resp.status_code == 400
    assert "cannot be negative" in resp.json()["detail"]

    # 7. Invalid customer_id type (e.g. dict or list)
    resp = client.post(
        "/v1/track",
        json={**base, "customer_id": {"id": 123}},
        headers={"X-API-Key": public_key},
    )
    assert resp.status_code == 400
    assert "customer_id" in resp.json()["detail"]

    # 8. Malformed JSON
    resp = client.post(
        "/v1/track",
        content=b"{not valid json",
        headers={"X-API-Key": public_key, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400

    # 9. Non-dict JSON body
    resp = client.post(
        "/v1/track",
        json=["not", "a", "dict"],
        headers={"X-API-Key": public_key},
    )
    assert resp.status_code == 400

    # Ensure zero invalid events reached the queue
    assert len(get_queued_events()) == 0


def test_track_authenticated_by_public_key_only(client: TestClient):
    """Confirm POST /v1/track requires a public key, rejecting private keys with 403."""
    valid_payload = {
        "event_type": "view",
        "session_id": "sess_1",
        "product_id": "prod_1",
    }

    # 1. Missing key -> 401
    resp_missing = client.post("/v1/track", json=valid_payload)
    assert resp_missing.status_code == 401

    # 2. Invalid key -> 401
    resp_invalid = client.post(
        "/v1/track",
        json=valid_payload,
        headers={"X-API-Key": "sk-completely-invalid"},
    )
    assert resp_invalid.status_code == 401

    # 3. Private key -> 403 Forbidden (authenticated by public key only)
    resp_private = client.post(
        "/v1/track",
        json=valid_payload,
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp_private.status_code == 403
    assert "public API key only" in resp_private.json()["detail"]

    # 4. Public key -> 202 Accepted
    resp_public = client.post(
        "/v1/track",
        json=valid_payload,
        headers={"X-API-Key": "pk-telco-xxxx"},
    )
    assert resp_public.status_code == 202

    # Only the 1 event with public key reached the queue
    queued = get_queued_events()
    assert len(queued) == 1
    assert queued[0]["tenant_id"] == "telco_default"
