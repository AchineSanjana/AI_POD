"""Tests for versioned /v1/ public-facing API routes, Pydantic schemas, and HTTP error codes."""

from __future__ import annotations

import io
from pathlib import Path
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.auth import TENANT_AUTH_MAPPING
from src.api.rate_limiter import RATE_LIMITER
from src.api.recommendations import get_model_for_tenant
from src.utils.config import load_config, resolve_path


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Ensure clean rate limits between tests."""
    RATE_LIMITER.reset()
    yield
    RATE_LIMITER.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Recommendations Tests (/v1/recommendations)
# ---------------------------------------------------------------------------


def test_v1_recommendations_success(client: TestClient):
    """GET /v1/recommendations returns 200 and matches RecommendationsResponse schema."""
    model = get_model_for_tenant("telco_default")
    customer_id = model.customers_.iloc[0]["customer_id"]

    resp = client.get(
        "/v1/recommendations",
        params={"customer_id": customer_id, "top_n": 3},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Schema verification
    assert data["tenant_id"] == "telco_default"
    assert data["customer_id"] == customer_id
    assert isinstance(data["recommendations"], list)
    assert len(data["recommendations"]) <= 3

    first_item = data["recommendations"][0]
    assert "rank" in first_item
    assert "product_id" in first_item
    assert "product_name" in first_item
    assert "category" in first_item
    assert first_item["rank"] == 1


def test_v1_recommendations_bad_input_400(client: TestClient):
    """GET /v1/recommendations returns 400 on blank customer_id or out-of-range top_n."""
    # Blank customer_id
    resp = client.get(
        "/v1/recommendations",
        params={"customer_id": "   ", "top_n": 5},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp.status_code == 400
    assert "cannot be blank" in resp.json()["detail"]

    # top_n < 1 (FastAPI validation)
    resp_top_n = client.get(
        "/v1/recommendations",
        params={"customer_id": "some_cust", "top_n": 0},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp_top_n.status_code == 422 or resp_top_n.status_code == 400


def test_v1_recommendations_unauthorized_401(client: TestClient):
    """GET /v1/recommendations returns 401 when X-API-Key is missing or invalid."""
    # Missing key
    resp_missing = client.get(
        "/v1/recommendations",
        params={"customer_id": "cust_1"},
    )
    assert resp_missing.status_code == 401
    assert "API key is missing" in resp_missing.json()["detail"]

    # Invalid key
    resp_invalid = client.get(
        "/v1/recommendations",
        params={"customer_id": "cust_1"},
        headers={"X-API-Key": "sk-bad-key"},
    )
    assert resp_invalid.status_code == 401
    assert "Invalid API Key" in resp_invalid.json()["detail"]


def test_v1_recommendations_unknown_customer_404(client: TestClient):
    """GET /v1/recommendations returns 404 when customer does not exist for tenant."""
    resp = client.get(
        "/v1/recommendations",
        params={"customer_id": "non_existent_cust_999999", "top_n": 3},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp.status_code == 404
    assert "not found for tenant" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Onboarding Workflow Tests (/v1/onboard/*)
# ---------------------------------------------------------------------------


def _cleanup_test_tenant(tenant_id: str) -> None:
    import shutil
    import yaml
    from src.api.onboarding import _ACTIVE_TRAINING_THREADS
    from src.utils.config import DEFAULT_CONFIG_PATH, resolve_path

    # Wait briefly for any active training thread for this tenant to finish
    th = _ACTIVE_TRAINING_THREADS.get(tenant_id)
    if th and th.is_alive():
        th.join(timeout=5)

    raw_f = resolve_path(f"data/raw/{tenant_id}_raw.csv")
    if raw_f.exists():
        raw_f.unlink(missing_ok=True)

    proc_dir = resolve_path(f"data/processed/{tenant_id}")
    if proc_dir.exists():
        shutil.rmtree(proc_dir, ignore_errors=True)

    model_dir = resolve_path(f"models/{tenant_id}")
    if model_dir.exists():
        shutil.rmtree(model_dir, ignore_errors=True)

    status_file = resolve_path(f"status/{tenant_id}.json")
    if status_file.exists():
        status_file.unlink(missing_ok=True)

    config_path = Path(DEFAULT_CONFIG_PATH)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if "tenants" in cfg and tenant_id in cfg["tenants"]:
            del cfg["tenants"][tenant_id]
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)


def test_v1_onboard_lifecycle_end_to_end(client: TestClient, tmp_path: Path, monkeypatch):
    """Verify complete onboarding lifecycle: upload -> validate -> confirm -> train -> status."""
    # Allow sufficient rate limit for multi-step onboarding lifecycle test
    monkeypatch.setattr(
        "src.api.rate_limiter.get_tenant_rate_limit",
        lambda t, scope="onboarding": 30,
    )

    # Register temporary test tenant key
    test_tenant = "v1_test_tenant"
    test_key = "sk-v1-test-xxxx"
    TENANT_AUTH_MAPPING[test_key] = test_tenant
    _cleanup_test_tenant(test_tenant)

    try:
        # Sample dataset
        sample_csv = (
            "user_id,account_age,subscription_tier,cloud_storage,security_backup\n"
            "u1,12,Pro,Yes,No\n"
            "u2,24,Enterprise,Yes,Yes\n"
            "u3,6,Basic,No,No\n"
            "u4,36,Enterprise,Yes,Yes\n"
            "u5,18,Pro,No,Yes\n"
        )

        # 1. POST /v1/onboard/upload
        upload_resp = client.post(
            "/v1/onboard/upload",
            json={"csv_content": sample_csv},
            headers={"X-API-Key": test_key},
        )
        assert upload_resp.status_code == 200
        up_data = upload_resp.json()
        assert up_data["tenant_id"] == test_tenant
        assert up_data["rows"] == 5
        assert "user_id" in up_data["columns"]
        assert "subscription_tier" in up_data["columns"]

        # 2. GET /v1/onboard/status (needs configuration)
        status_resp1 = client.get(
            "/v1/onboard/status",
            headers={"X-API-Key": test_key},
        )
        assert status_resp1.status_code == 200
        assert status_resp1.json()["status"] == "needs_configuration"
        assert status_resp1.json()["has_data"] is True
        assert status_resp1.json()["has_config"] is False

        # 3. POST /v1/onboard/validate
        val_resp = client.post(
            "/v1/onboard/validate",
            headers={"X-API-Key": test_key},
        )
        assert val_resp.status_code == 200
        val_data = val_resp.json()
        assert val_data["tenant_id"] == test_tenant
        assert val_data["is_valid"] is True
        assert "candidate_config" in val_data
        assert "summary" in val_data

        # 4. POST /v1/onboard/confirm
        candidate_cfg = val_data["candidate_config"]
        confirm_resp = client.post(
            "/v1/onboard/confirm",
            json={"candidate_config": candidate_cfg},
            headers={"X-API-Key": test_key},
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["config_saved"] is True

        # 5. GET /v1/onboard/status (ready to train)
        status_resp2 = client.get(
            "/v1/onboard/status",
            headers={"X-API-Key": test_key},
        )
        assert status_resp2.status_code == 200
        assert status_resp2.json()["status"] == "ready_to_train"
        assert status_resp2.json()["has_config"] is True

        # 6. POST /v1/onboard/train (returns 202 Accepted immediately)
        train_resp = client.post(
            "/v1/onboard/train",
            headers={"X-API-Key": test_key},
        )
        assert train_resp.status_code == 202
        tr_data = train_resp.json()
        assert tr_data["status"] == "queued"
        assert tr_data["status_url"] == "/v1/onboard/status"

        # Poll status until completion
        start_t = time.time()
        completed = False
        while time.time() - start_t < 15:
            st = client.get("/v1/onboard/status", headers={"X-API-Key": test_key}).json()
            if st["status"] == "complete":
                completed = True
                break
            time.sleep(0.1)

        assert completed is True, "Background training did not reach 'complete' in time"

        # 7. GET /v1/onboard/status (complete with model)
        status_resp3 = client.get(
            "/v1/onboard/status",
            headers={"X-API-Key": test_key},
        )
        assert status_resp3.status_code == 200
        assert status_resp3.json()["status"] == "complete"
        assert status_resp3.json()["has_model"] is True
        assert "final_model.joblib" in status_resp3.json()["model_path"]

    finally:
        TENANT_AUTH_MAPPING.pop(test_key, None)
        _cleanup_test_tenant(test_tenant)


def test_v1_onboard_upload_empty_400(client: TestClient):
    """POST /v1/onboard/upload returns 400 for empty data."""
    resp = client.post(
        "/v1/onboard/upload",
        json={"csv_content": ""},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp.status_code == 400
    assert "cannot be empty" in resp.json()["detail"]


def test_v1_onboard_validate_missing_data_404(client: TestClient):
    """POST /v1/onboard/validate returns 404 if no raw dataset exists for tenant."""
    dummy_key = "sk-no-data-xxxx"
    TENANT_AUTH_MAPPING[dummy_key] = "no_data_tenant"
    try:
        resp = client.post(
            "/v1/onboard/validate",
            headers={"X-API-Key": dummy_key},
        )
        assert resp.status_code == 404
        assert "No raw dataset found" in resp.json()["detail"]
    finally:
        TENANT_AUTH_MAPPING.pop(dummy_key, None)


def test_v1_onboard_train_missing_config_404(client: TestClient):
    """POST /v1/onboard/train returns 404 if tenant configuration is missing."""
    dummy_key = "sk-unconfigured-xxxx"
    TENANT_AUTH_MAPPING[dummy_key] = "unconfigured_tenant_123"
    try:
        resp = client.post(
            "/v1/onboard/train",
            headers={"X-API-Key": dummy_key},
        )
        assert resp.status_code == 404
        assert "not found in config.yaml" in resp.json()["detail"]
    finally:
        TENANT_AUTH_MAPPING.pop(dummy_key, None)


def test_v1_onboard_train_async_polling(client: TestClient, monkeypatch):
    """POST /v1/onboard/train returns 202 with status URL, transitions queued/running -> complete."""
    monkeypatch.setattr(
        "src.api.rate_limiter.get_tenant_rate_limit",
        lambda t, scope="onboarding": 30,
    )

    test_tenant = "v1_async_train_tenant"
    test_key = "sk-async-train-xxxx"
    TENANT_AUTH_MAPPING[test_key] = test_tenant
    _cleanup_test_tenant(test_tenant)

    try:
        sample_csv = (
            "user_id,account_age,subscription_tier,cloud_storage,security_backup\n"
            "u1,12,Pro,Yes,No\n"
            "u2,24,Enterprise,Yes,Yes\n"
            "u3,6,Basic,No,No\n"
            "u4,36,Enterprise,Yes,Yes\n"
            "u5,18,Pro,No,Yes\n"
        )
        up_resp = client.post(
            "/v1/onboard/upload",
            json={"csv_content": sample_csv},
            headers={"X-API-Key": test_key},
        )
        assert up_resp.status_code == 200

        val_resp = client.post(
            "/v1/onboard/validate",
            headers={"X-API-Key": test_key},
        )
        assert val_resp.status_code == 200

        conf_resp = client.post(
            "/v1/onboard/confirm",
            json={"candidate_config": val_resp.json()["candidate_config"]},
            headers={"X-API-Key": test_key},
        )
        assert conf_resp.status_code == 200

        # Start asynchronous training
        train_resp = client.post(
            "/v1/onboard/train",
            headers={"X-API-Key": test_key},
        )
        assert train_resp.status_code == 202
        train_data = train_resp.json()
        assert train_data["tenant_id"] == test_tenant
        assert train_data["status"] in ["queued", "running"]
        assert train_data["status_url"] == "/v1/onboard/status"

        # Poll status immediately: must be "queued" or "running"
        imm_resp = client.get(
            "/v1/onboard/status",
            headers={"X-API-Key": test_key},
        )
        assert imm_resp.status_code == 200
        imm_status = imm_resp.json()["status"]
        assert imm_status in ["queued", "running", "complete"]

        # Wait for completion
        start_time = time.time()
        final_resp = None
        while time.time() - start_time < 20:
            st = client.get("/v1/onboard/status", headers={"X-API-Key": test_key}).json()
            if st["status"] == "complete":
                final_resp = st
                break
            time.sleep(0.1)

        assert final_resp is not None, "Async training timed out before reaching 'complete'"
        assert final_resp["status"] == "complete"
        assert final_resp["has_model"] is True
        assert final_resp["model_path"] is not None
        assert "final_model.joblib" in final_resp["model_path"]
        assert final_resp["error"] is None

    finally:
        TENANT_AUTH_MAPPING.pop(test_key, None)
        _cleanup_test_tenant(test_tenant)


def test_v1_onboard_train_failure_captures_error(client: TestClient, monkeypatch):
    """Background training failure captures exception into status file and surfaces it."""
    monkeypatch.setattr(
        "src.api.rate_limiter.get_tenant_rate_limit",
        lambda t, scope="onboarding": 30,
    )

    test_tenant = "v1_fail_train_tenant"
    test_key = "sk-fail-train-xxxx"
    TENANT_AUTH_MAPPING[test_key] = test_tenant
    _cleanup_test_tenant(test_tenant)

    try:
        sample_csv = (
            "user_id,account_age,subscription_tier,cloud_storage,security_backup\n"
            "u1,12,Pro,Yes,No\n"
            "u2,24,Enterprise,Yes,Yes\n"
            "u3,6,Basic,No,No\n"
        )
        client.post(
            "/v1/onboard/upload",
            json={"csv_content": sample_csv},
            headers={"X-API-Key": test_key},
        )
        val_resp = client.post(
            "/v1/onboard/validate",
            headers={"X-API-Key": test_key},
        )
        client.post(
            "/v1/onboard/confirm",
            json={"candidate_config": val_resp.json()["candidate_config"]},
            headers={"X-API-Key": test_key},
        )

        # Force adapter to fail with specific error message
        def mock_failing_run(self):
            raise ValueError("Simulated corrupt data table schema in pipeline")

        monkeypatch.setattr(
            "src.data.adapters.generic_config_adapter.GenericConfigAdapter.run",
            mock_failing_run,
        )

        # Trigger training
        train_resp = client.post(
            "/v1/onboard/train",
            headers={"X-API-Key": test_key},
        )
        assert train_resp.status_code == 202

        # Poll status until failure is registered
        start_time = time.time()
        failed_resp = None
        while time.time() - start_time < 15:
            st = client.get("/v1/onboard/status", headers={"X-API-Key": test_key}).json()
            if st["status"] == "failed":
                failed_resp = st
                break
            time.sleep(0.1)

        assert failed_resp is not None, "Async training did not register 'failed' status in time"
        assert failed_resp["status"] == "failed"
        assert "Simulated corrupt data table schema in pipeline" in failed_resp["error"]
        assert "Simulated corrupt data table schema in pipeline" in failed_resp["message"]

    finally:
        TENANT_AUTH_MAPPING.pop(test_key, None)
        _cleanup_test_tenant(test_tenant)

