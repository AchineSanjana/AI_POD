"""Comprehensive regression and feature test suite for tenant recommendations improvements.

Covers:
1. New tenant right after training (fallback=false for known customer, model used immediately).
2. Unknown customer (HTTP 200, fallback=true, reason="unknown_customer").
3. Untrained tenant (HTTP 200, fallback=true, reason="model_not_trained").
4. Customer with no recommendation history (HTTP 200, fallback=true, reason="no_history").
5. Wrong or missing API keys (HTTP 401).
6. Public pk- keys forbidden on admin routes (HTTP 403) while allowed on recommendations.
7. Tenant isolation: two tenants never see each other's model, products, or customers.
8. Sample-customers endpoint: returns real IDs, tenant-scoped only, respects limit, works with pk- and sk- keys.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.auth import TENANT_AUTH_MAPPING, TENANT_KEY_RECORDS
from src.api.recommendations import clear_model_cache, get_model_for_tenant
from src.pipeline.run import run_tenant_pipeline
from src.storage.local_storage import LocalStorage
from src.utils.config import PROJECT_ROOT, get_tenant_config, load_config
from src.utils.persistence import save_model


class MockTenantModel:
    def __init__(
        self,
        customers_df: pd.DataFrame,
        products_df: pd.DataFrame,
        recommendations_list: list[str] | None = None,
    ):
        self.customers_ = customers_df
        self.products_ = products_df
        self._recs = recommendations_list or []

    def recommend(self, customer_id: str, top_k: int = 5):
        if self._recs:
            return self._recs[:top_k]
        return []


@pytest.fixture
def client(monkeypatch):
    clear_model_cache()
    monkeypatch.setattr(
        "src.api.rate_limiter.get_tenant_rate_limit",
        lambda t, scope="recommendations": 1000,
    )
    with TestClient(app) as test_client:
        yield test_client
    clear_model_cache()


def _cleanup_test_tenant(tenant_id: str):
    """Remove all test artifacts for a tenant."""
    for sub in [
        f"data/raw/{tenant_id}_raw.csv",
        f"status/{tenant_id}.json",
    ]:
        p = PROJECT_ROOT / sub
        if p.exists():
            p.unlink()

    for d in [
        f"data/processed/{tenant_id}",
        f"models/{tenant_id}",
    ]:
        dp = PROJECT_ROOT / d
        if dp.exists():
            shutil.rmtree(dp, ignore_errors=True)


def test_new_tenant_right_after_training_serves_model(client: TestClient):
    """Confirm that immediately after training finishes, first request uses the new model with fallback=False."""
    tenant_id = "test_fresh_trained_tenant"
    sk_key = "sk-test-fresh-sk"
    pk_key = "pk-test-fresh-pk"

    TENANT_AUTH_MAPPING[sk_key] = tenant_id
    TENANT_AUTH_MAPPING[pk_key] = tenant_id
    TENANT_KEY_RECORDS[sk_key] = {"tenant_id": tenant_id, "key_type": "private", "created_at": None}
    TENANT_KEY_RECORDS[pk_key] = {"tenant_id": tenant_id, "key_type": "public", "created_at": None}

    _cleanup_test_tenant(tenant_id)
    storage = LocalStorage()

    try:
        # 1. Create processed tenant tables
        customers_df = pd.DataFrame({"customer_id": ["user_101", "user_102", "user_103"]})
        products_df = pd.DataFrame({
            "product_id": ["prod_alpha", "prod_beta", "prod_gamma"],
            "product_name": ["Alpha Widget", "Beta Gadget", "Gamma Tool"],
            "category": ["Hardware", "Hardware", "Tools"],
        })
        interactions_df = pd.DataFrame({
            "customer_id": ["user_101", "user_102"],
            "product_id": ["prod_alpha", "prod_beta"],
        })

        storage.write_file(f"data/processed/{tenant_id}/customers.csv", customers_df.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{tenant_id}/products.csv", products_df.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{tenant_id}/interactions.csv", interactions_df.to_csv(index=False).encode("utf-8"))

        # Save model to models/{tenant_id}/final_model.joblib
        model_path = f"models/{tenant_id}/final_model.joblib"
        save_model(
            MockTenantModel(customers_df, products_df, ["prod_alpha", "prod_beta"]),
            model_path,
            storage=storage,
        )
        clear_model_cache()

        # 2. First request immediately after training must use model
        resp = client.get(
            "/v1/recommendations/user_101",
            headers={"X-API-Key": pk_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == tenant_id
        assert data["customer_id"] == "user_101"
        assert data["fallback"] is False
        assert data["reason"] is None
        assert len(data["recommendations"]) == 2
        assert data["recommendations"][0]["product_id"] == "prod_alpha"
        assert data["recommendations"][0]["product_name"] == "Alpha Widget"
        assert data["recommendations"][0]["category"] == "Hardware"

    finally:
        TENANT_AUTH_MAPPING.pop(sk_key, None)
        TENANT_AUTH_MAPPING.pop(pk_key, None)
        TENANT_KEY_RECORDS.pop(sk_key, None)
        TENANT_KEY_RECORDS.pop(pk_key, None)
        _cleanup_test_tenant(tenant_id)


def test_unknown_customer_returns_200_with_fallback_and_reason(client: TestClient):
    """Unknown customer on trained tenant returns HTTP 200 with fallback=True and reason='unknown_customer'."""
    resp = client.get(
        "/v1/recommendations/completely_unknown_customer_xyz",
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == "telco_default"
    assert data["customer_id"] == "completely_unknown_customer_xyz"
    assert data["fallback"] is True
    assert data["reason"] == "unknown_customer"
    assert isinstance(data["recommendations"], list)
    assert len(data["recommendations"]) > 0


def test_untrained_tenant_returns_200_with_fallback_and_reason(client: TestClient):
    """Untrained tenant returns HTTP 200 with popularity fallback and reason='model_not_trained'."""
    tenant_id = "untrained_tenant_demo"
    key = "sk-untrained-demo-key"
    TENANT_AUTH_MAPPING[key] = tenant_id
    TENANT_KEY_RECORDS[key] = {"tenant_id": tenant_id, "key_type": "private", "created_at": None}
    _cleanup_test_tenant(tenant_id)

    try:
        resp = client.get(
            "/v1/recommendations/any_customer_id",
            headers={"X-API-Key": key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == tenant_id
        assert data["customer_id"] == "any_customer_id"
        assert data["fallback"] is True
        assert data["reason"] == "model_not_trained"
        assert isinstance(data["recommendations"], list)
    finally:
        TENANT_AUTH_MAPPING.pop(key, None)
        TENANT_KEY_RECORDS.pop(key, None)
        _cleanup_test_tenant(tenant_id)


def test_customer_no_history_returns_fallback_reason(client: TestClient):
    """Customer exists in dataset but has no interaction history and model returns empty -> fallback with reason='no_history'."""
    tenant_id = "test_no_history_tenant"
    key = "sk-no-history-key"
    TENANT_AUTH_MAPPING[key] = tenant_id
    TENANT_KEY_RECORDS[key] = {"tenant_id": tenant_id, "key_type": "private", "created_at": None}
    _cleanup_test_tenant(tenant_id)
    storage = LocalStorage()

    try:
        customers_df = pd.DataFrame({"customer_id": ["user_with_no_history"]})
        products_df = pd.DataFrame({"product_id": ["p1"], "product_name": ["Prod 1"], "category": ["Cat 1"]})
        storage.write_file(f"data/processed/{tenant_id}/customers.csv", customers_df.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{tenant_id}/products.csv", products_df.to_csv(index=False).encode("utf-8"))

        save_model(
            MockTenantModel(customers_df, products_df, []),
            f"models/{tenant_id}/final_model.joblib",
            storage=storage,
        )
        clear_model_cache()

        resp = client.get(
            "/v1/recommendations/user_with_no_history",
            headers={"X-API-Key": key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fallback"] is True
        assert data["reason"] == "no_history"
    finally:
        TENANT_AUTH_MAPPING.pop(key, None)
        TENANT_KEY_RECORDS.pop(key, None)
        _cleanup_test_tenant(tenant_id)


def test_wrong_and_missing_api_keys(client: TestClient):
    """Missing key or invalid key returns HTTP 401."""
    # Missing key
    resp_missing = client.get("/v1/recommendations/cust1")
    assert resp_missing.status_code == 401
    assert "API key is missing" in resp_missing.json()["detail"]

    # Invalid key
    resp_invalid = client.get(
        "/v1/recommendations/cust1",
        headers={"X-API-Key": "sk-completely-invalid-key"},
    )
    assert resp_invalid.status_code == 401
    assert "Invalid API Key" in resp_invalid.json()["detail"]


def test_public_key_permissions(client: TestClient):
    """pk- public key is permitted for recommendations & sample-customers, but blocked from admin routes (HTTP 403)."""
    pk_key = "pk-telco-xxxx"

    # 1. Allowed on GET /v1/recommendations
    resp_recs = client.get(
        "/v1/recommendations",
        params={"customer_id": "cust1"},
        headers={"X-API-Key": pk_key},
    )
    assert resp_recs.status_code == 200

    # 2. Allowed on GET /v1/recommendations/{id}
    resp_recs_id = client.get(
        "/v1/recommendations/cust1",
        headers={"X-API-Key": pk_key},
    )
    assert resp_recs_id.status_code == 200

    # 3. Allowed on GET /v1/recommendations/sample-customers
    resp_samples = client.get(
        "/v1/recommendations/sample-customers",
        headers={"X-API-Key": pk_key},
    )
    assert resp_samples.status_code == 200

    # 4. Forbidden on admin routes (HTTP 403)
    resp_status = client.get("/v1/onboard/status", headers={"X-API-Key": pk_key})
    assert resp_status.status_code == 403

    resp_train = client.post("/v1/onboard/train", headers={"X-API-Key": pk_key})
    assert resp_train.status_code == 403


def test_tenant_isolation_never_shares_models_or_products(client: TestClient):
    """Two tenants never see each other's model, products, or customers."""
    tenant_a = "tenant_isolation_a"
    tenant_b = "tenant_isolation_b"
    key_a = "sk-tenant-a-key"
    key_b = "sk-tenant-b-key"

    TENANT_AUTH_MAPPING[key_a] = tenant_a
    TENANT_AUTH_MAPPING[key_b] = tenant_b
    TENANT_KEY_RECORDS[key_a] = {"tenant_id": tenant_a, "key_type": "private", "created_at": None}
    TENANT_KEY_RECORDS[key_b] = {"tenant_id": tenant_b, "key_type": "private", "created_at": None}

    _cleanup_test_tenant(tenant_a)
    _cleanup_test_tenant(tenant_b)
    storage = LocalStorage()

    try:
        # Tenant A data & model
        df_cust_a = pd.DataFrame({"customer_id": ["user_a1", "user_a2"]})
        df_prod_a = pd.DataFrame({"product_id": ["prod_a1", "prod_a2"], "product_name": ["Prod A1", "Prod A2"], "category": ["Cat A", "Cat A"]})
        storage.write_file(f"data/processed/{tenant_a}/customers.csv", df_cust_a.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{tenant_a}/products.csv", df_prod_a.to_csv(index=False).encode("utf-8"))

        save_model(
            MockTenantModel(df_cust_a, df_prod_a, ["prod_a1"]),
            f"models/{tenant_a}/final_model.joblib",
            storage=storage,
        )

        # Tenant B data & model
        df_cust_b = pd.DataFrame({"customer_id": ["user_b1", "user_b2"]})
        df_prod_b = pd.DataFrame({"product_id": ["prod_b1", "prod_b2"], "product_name": ["Prod B1", "Prod B2"], "category": ["Cat B", "Cat B"]})
        storage.write_file(f"data/processed/{tenant_b}/customers.csv", df_cust_b.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{tenant_b}/products.csv", df_prod_b.to_csv(index=False).encode("utf-8"))

        save_model(
            MockTenantModel(df_cust_b, df_prod_b, ["prod_b1"]),
            f"models/{tenant_b}/final_model.joblib",
            storage=storage,
        )
        clear_model_cache()

        # Tenant A query for user_a1 -> strictly Tenant A's products
        resp_a = client.get("/v1/recommendations/user_a1", headers={"X-API-Key": key_a})
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert data_a["tenant_id"] == tenant_a
        assert data_a["fallback"] is False
        assert [r["product_id"] for r in data_a["recommendations"]] == ["prod_a1"]

        # Tenant B query for user_b1 -> strictly Tenant B's products
        resp_b = client.get("/v1/recommendations/user_b1", headers={"X-API-Key": key_b})
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["tenant_id"] == tenant_b
        assert data_b["fallback"] is False
        assert [r["product_id"] for r in data_b["recommendations"]] == ["prod_b1"]

        # Cross-query: Querying user_b1 with Tenant A's key must return Tenant A's fallback, NEVER Tenant B's data
        resp_cross = client.get("/v1/recommendations/user_b1", headers={"X-API-Key": key_a})
        assert resp_cross.status_code == 200
        data_cross = resp_cross.json()
        assert data_cross["tenant_id"] == tenant_a
        assert data_cross["fallback"] is True
        assert data_cross["reason"] == "unknown_customer"
        # Must not contain any Tenant B product
        cross_ids = {r["product_id"] for r in data_cross["recommendations"]}
        assert "prod_b1" not in cross_ids
        assert "prod_b2" not in cross_ids

    finally:
        TENANT_AUTH_MAPPING.pop(key_a, None)
        TENANT_AUTH_MAPPING.pop(key_b, None)
        TENANT_KEY_RECORDS.pop(key_a, None)
        TENANT_KEY_RECORDS.pop(key_b, None)
        _cleanup_test_tenant(tenant_a)
        _cleanup_test_tenant(tenant_b)


def test_sample_customers_endpoint_own_tenant_only(client: TestClient):
    """GET /v1/recommendations/sample-customers returns real IDs scoped strictly to authenticated tenant."""
    tenant_id = "test_sample_cust_tenant"
    sk_key = "sk-sample-cust-sk"
    pk_key = "pk-sample-cust-pk"

    TENANT_AUTH_MAPPING[sk_key] = tenant_id
    TENANT_AUTH_MAPPING[pk_key] = tenant_id
    TENANT_KEY_RECORDS[sk_key] = {"tenant_id": tenant_id, "key_type": "private", "created_at": None}
    TENANT_KEY_RECORDS[pk_key] = {"tenant_id": tenant_id, "key_type": "public", "created_at": None}

    _cleanup_test_tenant(tenant_id)
    storage = LocalStorage()

    try:
        # Create processed customers.csv
        sample_ids = [f"cust_{i}" for i in range(1, 25)]
        df = pd.DataFrame({"customer_id": sample_ids, "age": [20 + i for i in range(24)]})
        storage.write_file(f"data/processed/{tenant_id}/customers.csv", df.to_csv(index=False).encode("utf-8"))

        # Test with limit=5 via public key
        resp_pk = client.get(
            "/v1/recommendations/sample-customers?limit=5",
            headers={"X-API-Key": pk_key},
        )
        assert resp_pk.status_code == 200
        data_pk = resp_pk.json()
        assert data_pk["tenant_id"] == tenant_id
        assert len(data_pk["customer_ids"]) == 5
        assert data_pk["customer_ids"] == sample_ids[:5]

        # Test with limit=10 via private key
        resp_sk = client.get(
            "/v1/recommendations/sample-customers?limit=10",
            headers={"X-API-Key": sk_key},
        )
        assert resp_sk.status_code == 200
        data_sk = resp_sk.json()
        assert data_sk["tenant_id"] == tenant_id
        assert len(data_sk["customer_ids"]) == 10
        assert data_sk["customer_ids"] == sample_ids[:10]

    finally:
        TENANT_AUTH_MAPPING.pop(sk_key, None)
        TENANT_AUTH_MAPPING.pop(pk_key, None)
        TENANT_KEY_RECORDS.pop(sk_key, None)
        TENANT_KEY_RECORDS.pop(pk_key, None)
        _cleanup_test_tenant(tenant_id)
