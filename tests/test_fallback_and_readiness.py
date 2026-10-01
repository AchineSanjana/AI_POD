"""Tests for recommendation fallback on untrained tenants and training readiness checking (Step 21.2).

Verifies:
1. Before a tenant has ever been trained, GET /v1/recommendations does not error and returns
   the tenant's most-frequently-interacted-with products with fallback: True.
2. An untrained tenant below threshold is NOT marked ready-to-train.
3. An untrained tenant crossing thresholds (MIN_CUSTOMERS_TO_TRAIN, MIN_INTERACTIONS_TO_TRAIN)
   is marked as ready_to_train in status storage and via GET /v1/onboard/status.
4. BackgroundScheduler executes the training_readiness_check scheduled job.
5. Trained tenants return personalized recommendations with fallback: False.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.auth import TENANT_AUTH_MAPPING
from src.api.recommendations import clear_model_cache
from src.api.tracking import clear_queue, push_event
from src.scheduler.readiness_checker import (
    check_untrained_tenants_readiness,
    get_tenant_customer_and_interaction_counts,
    is_tenant_untrained,
)
from src.scheduler.scheduler import get_scheduler
from src.storage import get_storage_backend
from src.utils.config import (
    MIN_CUSTOMERS_TO_TRAIN,
    MIN_INTERACTIONS_TO_TRAIN,
    get_training_thresholds,
    load_config,
    resolve_path,
)


@pytest.fixture
def client():
    clear_model_cache()
    clear_queue()
    with TestClient(app) as test_client:
        yield test_client
    clear_model_cache()
    clear_queue()


def _cleanup_tenant(tenant_id: str, storage=None):
    if storage is None:
        storage = get_storage_backend()
    for sub in [
        f"data/processed/{tenant_id}/interactions.csv",
        f"data/processed/{tenant_id}/customers.csv",
        f"data/processed/{tenant_id}/products.csv",
        f"models/{tenant_id}/final_model.joblib",
        f"status/{tenant_id}.json",
    ]:
        try:
            if storage.exists(sub):
                storage.delete_file(sub)
        except Exception:
            pass

    for p in [
        resolve_path(f"data/processed/{tenant_id}"),
        resolve_path(f"models/{tenant_id}"),
        resolve_path(f"status/{tenant_id}.json"),
    ]:
        if p.is_file():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            for child in p.glob("*"):
                child.unlink(missing_ok=True)
            p.rmdir()


def test_training_threshold_constants_and_config():
    """Verify default constants and config resolution."""
    assert MIN_CUSTOMERS_TO_TRAIN == 50
    assert MIN_INTERACTIONS_TO_TRAIN == 200

    config = load_config()
    min_c, min_i = get_training_thresholds(config)
    assert min_c == 50
    assert min_i == 200


def test_untrained_tenant_below_threshold_fallback(client: TestClient):
    """Test a tenant below threshold: confirms fallback response with top products and fallback: True."""
    tenant_id = "tenant_test_below"
    api_key = "sk-below-threshold-key"
    storage = get_storage_backend()

    try:
        _cleanup_tenant(tenant_id, storage=storage)
        TENANT_AUTH_MAPPING[api_key] = tenant_id

        # 1. Setup a handful of interactions below threshold:
        # 5 interactions across 2 products: prod_A (3 times), prod_B (2 times)
        interactions_df = pd.DataFrame(
            [
                {"customer_id": "cust_1", "product_id": "prod_B"},
                {"customer_id": "cust_1", "product_id": "prod_A"},
                {"customer_id": "cust_2", "product_id": "prod_A"},
                {"customer_id": "cust_2", "product_id": "prod_B"},
                {"customer_id": "cust_2", "product_id": "prod_A"},
            ]
        )
        products_df = pd.DataFrame(
            [
                {"product_id": "prod_A", "product_name": "Alpha Service", "category": "Core"},
                {"product_id": "prod_B", "product_name": "Beta Addon", "category": "Add-on"},
            ]
        )

        storage.write_file(
            f"data/processed/{tenant_id}/interactions.csv",
            interactions_df.to_csv(index=False).encode("utf-8"),
        )
        storage.write_file(
            f"data/processed/{tenant_id}/products.csv",
            products_df.to_csv(index=False).encode("utf-8"),
        )

        assert is_tenant_untrained(tenant_id, storage=storage) is True

        # 2. Call GET /v1/recommendations for untrained tenant with arbitrary customer
        resp = client.get(
            "/v1/recommendations",
            params={"customer_id": "guest_customer_999", "top_n": 5},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["tenant_id"] == tenant_id
        assert data["customer_id"] == "guest_customer_999"
        assert data["fallback"] is True
        assert isinstance(data["recommendations"], list)
        assert len(data["recommendations"]) == 2

        # Most frequent product (prod_A with 3 interactions) must be rank 1
        rec1 = data["recommendations"][0]
        assert rec1["rank"] == 1
        assert rec1["product_id"] == "prod_A"
        assert rec1["product_name"] == "Alpha Service"
        assert rec1["category"] == "Core"

        # Second most frequent product (prod_B with 2 interactions) must be rank 2
        rec2 = data["recommendations"][1]
        assert rec2["rank"] == 2
        assert rec2["product_id"] == "prod_B"
        assert rec2["product_name"] == "Beta Addon"
        assert rec2["category"] == "Add-on"

        # 3. Also verify GET /recommendations legacy endpoint returns fallback
        legacy_resp = client.get(
            "/recommendations",
            params={"customer_id": "guest_customer_999", "top_n": 2},
            headers={"X-API-Key": api_key},
        )
        assert legacy_resp.status_code == 200
        assert legacy_resp.json()["fallback"] is True

        # 4. Run the checker: tenant is below threshold (2 customers < 50, 5 interactions < 200)
        c_count, i_count = get_tenant_customer_and_interaction_counts(tenant_id, storage=storage)
        assert c_count == 2
        assert i_count == 5

        results = check_untrained_tenants_readiness(
            storage=storage,
            min_customers=50,
            min_interactions=200,
        )
        assert tenant_id in results["below_threshold"]
        assert tenant_id not in results["marked_ready"]

        # Confirm status file was NOT created or marked ready_to_train
        assert not storage.exists(f"status/{tenant_id}.json")

    finally:
        TENANT_AUTH_MAPPING.pop(api_key, None)
        _cleanup_tenant(tenant_id, storage=storage)


def test_untrained_tenant_just_crossing_threshold_marked_ready_to_train(client: TestClient):
    """Test a tenant just crossing thresholds: confirms it gets marked as ready-to-train."""
    tenant_id = "tenant_test_crossing"
    api_key = "sk-crossing-threshold-key"
    storage = get_storage_backend()

    try:
        _cleanup_tenant(tenant_id, storage=storage)
        TENANT_AUTH_MAPPING[api_key] = tenant_id

        # 1. Populate exactly 50 unique customers and 200 interactions (matching default thresholds)
        customers_list = [f"cust_{i:03d}" for i in range(1, 51)]  # 50 unique customers
        interactions_list = []
        for i in range(200):
            cust = customers_list[i % 50]
            prod = f"prod_{i % 10}"
            interactions_list.append({"customer_id": cust, "product_id": prod})

        interactions_df = pd.DataFrame(interactions_list)
        customers_df = pd.DataFrame([{"customer_id": c} for c in customers_list])

        storage.write_file(
            f"data/processed/{tenant_id}/interactions.csv",
            interactions_df.to_csv(index=False).encode("utf-8"),
        )
        storage.write_file(
            f"data/processed/{tenant_id}/customers.csv",
            customers_df.to_csv(index=False).encode("utf-8"),
        )

        assert is_tenant_untrained(tenant_id, storage=storage) is True

        c_count, i_count = get_tenant_customer_and_interaction_counts(tenant_id, storage=storage)
        assert c_count == 50
        assert i_count == 200

        # Status before checker runs
        assert not storage.exists(f"status/{tenant_id}.json")

        # 2. Run the readiness checker (Step 21.2)
        results = check_untrained_tenants_readiness(
            storage=storage,
            min_customers=50,
            min_interactions=200,
        )

        assert tenant_id in results["marked_ready"]
        assert tenant_id not in results["below_threshold"]

        # 3. Confirm status file is saved as ready_to_train
        status_file_path = f"status/{tenant_id}.json"
        assert storage.exists(status_file_path)
        status_data = json.loads(storage.read_file(status_file_path).decode("utf-8"))
        assert status_data["status"] == "ready_to_train"
        assert status_data["tenant_id"] == tenant_id
        assert status_data["customers_count"] == 50
        assert status_data["interactions_count"] == 200

        # 4. Confirm GET /v1/onboard/status reflects ready_to_train
        st_resp = client.get("/v1/onboard/status", headers={"X-API-Key": api_key})
        assert st_resp.status_code == 200
        st_payload = st_resp.json()
        assert st_payload["status"] == "ready_to_train"
        assert st_payload["tenant_id"] == tenant_id

        # 5. Confirm recommendations endpoint still returns fallback until actually trained
        rec_resp = client.get(
            "/v1/recommendations",
            params={"customer_id": "cust_001", "top_n": 3},
            headers={"X-API-Key": api_key},
        )
        assert rec_resp.status_code == 200
        assert rec_resp.json()["fallback"] is True
        assert len(rec_resp.json()["recommendations"]) == 3

    finally:
        TENANT_AUTH_MAPPING.pop(api_key, None)
        _cleanup_tenant(tenant_id, storage=storage)


def test_scheduler_job_step_21_2():
    """Verify that BackgroundScheduler registers and executes the Step 21.2 training readiness check."""
    scheduler = get_scheduler()
    assert "training_readiness_check" in scheduler.jobs

    job = scheduler.jobs["training_readiness_check"]
    assert job.interval_seconds > 0

    # Execute job immediately via scheduler
    result = scheduler.run_job_now("training_readiness_check")
    assert isinstance(result, dict)
    assert "checked" in result
    assert "marked_ready" in result
    assert "below_threshold" in result


def test_trained_tenant_returns_fallback_false(client: TestClient):
    """Verify that a trained tenant (e.g. telco_default) returns personalized recommendations with fallback: False."""
    resp = client.get(
        "/v1/recommendations",
        params={"customer_id": "7590-VHVEG", "top_n": 3},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == "telco_default"
    assert data["fallback"] is False
    assert len(data["recommendations"]) <= 3
