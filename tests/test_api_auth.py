"""Tests for API Key authentication, header validation, and tenant isolation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.auth import TENANT_AUTH_MAPPING, get_current_tenant, load_tenant_auth
from src.api.recommendations import get_model_for_tenant


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_auth_mapping_loaded_from_config():
    """Verify tenants_auth mapping from config.yaml is properly loaded."""
    mapping = load_tenant_auth()
    assert isinstance(mapping, dict)
    assert "sk-telco-xxxx" in mapping
    assert mapping["sk-telco-xxxx"] == "telco_default"
    assert "sk-ecommerce-xxxx" in mapping
    assert mapping["sk-ecommerce-xxxx"] == "fixture_ecommerce"


def test_valid_api_key_resolves_to_tenant(client: TestClient):
    """Confirm a valid API key in X-API-Key header resolves to the mapped tenant_id."""
    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    # Test GET endpoint with telco key
    resp_telco = client.get(
        "/recommendations",
        params={"customer_id": customer_id, "top_n": 2},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp_telco.status_code == 200
    assert resp_telco.json()["tenant_id"] == "telco_default"

    # Test GET /{customer_id} endpoint with ecommerce key
    ecom_model = get_model_for_tenant("fixture_ecommerce")
    ecom_customer_id = ecom_model.customers_.iloc[0]["customer_id"]

    resp_ecom = client.get(
        f"/recommendations/{ecom_customer_id}",
        headers={"X-API-Key": "sk-ecommerce-xxxx"},
    )
    assert resp_ecom.status_code == 200
    assert resp_ecom.json()["tenant_id"] == "fixture_ecommerce"


def test_missing_api_key_rejected_with_401(client: TestClient):
    """Confirm request with missing X-API-Key is rejected with 401 Unauthorized and clear JSON."""
    # GET /recommendations
    resp = client.get("/recommendations", params={"customer_id": "any_customer"})
    assert resp.status_code == 401
    error = resp.json()
    assert "detail" in error
    assert "API key is missing" in error["detail"]

    # GET /recommendations/{customer_id}
    resp_path = client.get("/recommendations/any_customer")
    assert resp_path.status_code == 401
    assert "API key is missing" in resp_path.json()["detail"]

    # POST /recommendations
    resp_post = client.post("/recommendations", json={"customer_id": "any_customer"})
    assert resp_post.status_code == 401
    assert "API key is missing" in resp_post.json()["detail"]


def test_invalid_api_key_rejected_with_401(client: TestClient):
    """Confirm request with invalid X-API-Key is rejected with 401 Unauthorized and clear JSON."""
    resp = client.get(
        "/recommendations",
        params={"customer_id": "any_customer"},
        headers={"X-API-Key": "sk-totally-bogus-key"},
    )
    assert resp.status_code == 401
    error = resp.json()
    assert "detail" in error
    assert "Invalid API Key" in error["detail"]


def test_cross_tenant_spoofing_prevented_in_body_and_query(client: TestClient):
    """Confirm a request with key for Tenant A cannot access Tenant B's data via body or query.

    Even if caller specifies tenant_id='fixture_ecommerce' in the request body (POST)
    or query string (GET), the system strictly binds the request to 'telco_default'.
    """
    telco_model = get_model_for_tenant("telco_default")
    telco_cust = telco_model.customers_.iloc[0]["customer_id"]
    telco_products = set(telco_model.products_["product_id"].astype(str))

    ecom_model = get_model_for_tenant("fixture_ecommerce")
    ecom_products = set(ecom_model.products_["product_id"].astype(str))

    # Assert catalogs are disjoint
    assert telco_products.isdisjoint(ecom_products)

    # 1. POST attempt to spoof tenant_id in JSON body
    post_resp = client.post(
        "/recommendations",
        json={
            "customer_id": telco_cust,
            "tenant_id": "fixture_ecommerce",
            "top_n": 3,
        },
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    # Server-side resolved tenant must strictly be telco_default
    assert post_data["tenant_id"] == "telco_default"
    rec_ids = {str(r["product_id"]) for r in post_data["recommendations"]}
    assert rec_ids.issubset(telco_products)
    assert rec_ids.isdisjoint(ecom_products)

    # 2. GET attempt to spoof tenant_id in query params
    get_resp = client.get(
        "/recommendations",
        params={
            "customer_id": telco_cust,
            "tenant_id": "fixture_ecommerce",
            "top_n": 3,
        },
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["tenant_id"] == "telco_default"
    get_rec_ids = {str(r["product_id"]) for r in get_data["recommendations"]}
    assert get_rec_ids.issubset(telco_products)
    assert get_rec_ids.isdisjoint(ecom_products)

    # 3. Attempting to query Tenant B's customer ID using Tenant A's key must return 404
    ecom_cust = ecom_model.customers_.iloc[0]["customer_id"]
    cross_resp = client.post(
        "/recommendations",
        json={
            "customer_id": ecom_cust,
            "tenant_id": "fixture_ecommerce",
        },
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert cross_resp.status_code == 404
    assert f"Customer '{ecom_cust}' not found for tenant 'telco_default'" in cross_resp.json()["detail"]
