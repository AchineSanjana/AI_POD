"""End-to-end integration tests for multi-model onboarding tournament pipeline.

Covers:
1. Complete onboarding lifecycle on local storage: upload -> validate -> confirm -> train -> poll to completion.
2. Complete onboarding lifecycle on S3 storage (mocked with moto).
3. Multi-worker collision guard (HTTP 409 on second /train call within 15 minutes).
4. Stalled job detection (reports status='stalled' when running >15 minutes).
5. Multi-worker model cache safety with 30s TTL and version marker reload.
6. Startup JWT secret enforcement in production environment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
import os
import sys
import time
from pathlib import Path

import boto3
from fastapi.testclient import TestClient
from moto import mock_aws
import pandas as pd
import pytest

from src.api.app import app, lifespan
from src.api.auth import TENANT_AUTH_MAPPING
from src.api.recommendations import (
    MODEL_CACHE,
    MODEL_CACHE_METADATA,
    clear_model_cache,
    get_model_for_tenant,
)
from src.pipeline.run import run_tenant_pipeline
from src.storage import get_storage_backend
from src.storage.local_storage import LocalStorage
from src.storage.s3_storage import S3Storage
from src.utils import config as config_module
from src.utils.persistence import save_model


class DummyModel:
    def __init__(self, version: str):
        self.version = version
        self.customers_ = pd.DataFrame({"customer_id": ["c1", "c2"]})
        self.products_ = pd.DataFrame({"product_id": ["p1", "p2"], "product_name": ["Prod 1", "Prod 2"]})

    def recommend(self, customer_id: str, top_k: int = 5):
        return ["p1", "p2"]


@pytest.fixture
def test_client(monkeypatch):
    """Provide a TestClient with rate limits lifted."""
    clear_model_cache()
    monkeypatch.setattr(
        "src.api.rate_limiter.get_tenant_rate_limit",
        lambda t, scope="onboarding": 1000,
    )
    with TestClient(app) as client:
        yield client
    clear_model_cache()


def _cleanup_tenant_files(tenant_id: str):
    """Clean up local test tenant files from disk."""
    from src.utils.config import PROJECT_ROOT

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
            import shutil
            shutil.rmtree(dp, ignore_errors=True)


SAMPLE_DATASET_CSV = (
    "customer_id,account_age,plan_tier,cloud_storage,security_backup,streaming_tv\n"
    "c1,12,Pro,Yes,No,Yes\n"
    "c2,24,Enterprise,Yes,Yes,No\n"
    "c3,6,Basic,No,No,Yes\n"
    "c4,36,Enterprise,Yes,Yes,Yes\n"
    "c5,18,Pro,No,Yes,No\n"
    "c6,20,Pro,Yes,Yes,No\n"
    "c7,14,Basic,No,No,No\n"
    "c8,40,Enterprise,Yes,No,Yes\n"
)


def test_onboarding_lifecycle_local_e2e(test_client: TestClient, monkeypatch):
    """Test full onboarding wizard lifecycle on local storage backend."""
    tenant_id = "test_onboard_local"
    key = "sk-test-local-key"
    TENANT_AUTH_MAPPING[key] = tenant_id
    _cleanup_tenant_files(tenant_id)

    try:
        # 1. Initial status before anything exists
        s0 = test_client.get("/v1/onboard/status", headers={"X-API-Key": key})
        assert s0.status_code == 200
        assert s0.json()["status"] == "not_started"
        assert s0.json()["ready"] is False

        # 2. Upload dataset via storage
        up_resp = test_client.post(
            "/v1/onboard/upload",
            json={"csv_content": SAMPLE_DATASET_CSV},
            headers={"X-API-Key": key},
        )
        assert up_resp.status_code == 200
        up_json = up_resp.json()
        assert up_json["tenant_id"] == tenant_id
        assert up_json["rows"] == 8

        # 3. Validate dataset
        val_resp = test_client.post(
            "/v1/onboard/validate",
            headers={"X-API-Key": key},
        )
        assert val_resp.status_code == 200
        val_json = val_resp.json()
        assert val_json["tenant_id"] == tenant_id
        candidate_cfg = val_json["candidate_config"]
        assert "customers" in candidate_cfg

        # 4. Confirm configuration
        conf_resp = test_client.post(
            "/v1/onboard/confirm",
            json={"candidate_config": candidate_cfg},
            headers={"X-API-Key": key},
        )
        assert conf_resp.status_code == 200
        assert conf_resp.json()["config_saved"] is True

        # 5. Status is now ready_to_train
        s1 = test_client.get("/v1/onboard/status", headers={"X-API-Key": key})
        assert s1.status_code == 200
        assert s1.json()["status"] == "ready_to_train"

        # 6. Trigger training
        tr_resp = test_client.post("/v1/onboard/train", headers={"X-API-Key": key})
        assert tr_resp.status_code == 202
        assert tr_resp.json()["status"] == "queued"

        # 7. Second train call immediately returns 409 Conflict
        tr_conflict = test_client.post("/v1/onboard/train", headers={"X-API-Key": key})
        assert tr_conflict.status_code == 409

        # 8. Poll until tournament completed
        start_t = time.time()
        final_status = None
        while time.time() - start_t < 30:
            st = test_client.get("/v1/onboard/status", headers={"X-API-Key": key}).json()
            if st.get("status") in ("completed", "complete"):
                final_status = st
                break
            time.sleep(0.3)

        assert final_status is not None, "Tournament pipeline did not complete in time"
        assert final_status["ready"] is True
        assert final_status["winner_model"] is not None
        assert final_status["winner_key"] in ["content", "collaborative", "hybrid", "xgboost"]
        assert "models" in final_status
        assert final_status["dataset"]["customers"] > 0

    finally:
        TENANT_AUTH_MAPPING.pop(key, None)
        _cleanup_tenant_files(tenant_id)


@mock_aws
def test_onboarding_lifecycle_s3_e2e(test_client: TestClient, monkeypatch):
    """Test full onboarding wizard lifecycle on S3 storage backend."""
    bucket_name = "onboard-s3-e2e-bucket"
    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket=bucket_name)

    orig_load_config = config_module.load_config

    def mock_s3_config():
        cfg = orig_load_config()
        cfg["storage"] = {
            "backend": "s3",
            "s3_bucket": bucket_name,
            "s3_prefix": "",
        }
        return cfg

    monkeypatch.setattr(config_module, "load_config", mock_s3_config)
    monkeypatch.setattr("src.api.onboarding.load_config", mock_s3_config)
    monkeypatch.setattr("src.api.recommendations.load_config", mock_s3_config)
    monkeypatch.setattr("src.pipeline.run.load_config", mock_s3_config)

    tenant_id = "test_onboard_s3"
    key = "sk-test-s3-key"
    TENANT_AUTH_MAPPING[key] = tenant_id

    try:
        # 1. Upload raw dataset to S3 through onboarding API
        up_resp = test_client.post(
            "/v1/onboard/upload",
            json={"csv_content": SAMPLE_DATASET_CSV},
            headers={"X-API-Key": key},
        )
        assert up_resp.status_code == 200

        s3_storage = S3Storage(bucket_name=bucket_name, s3_client=s3_client)
        assert s3_storage.exists(f"data/raw/{tenant_id}_raw.csv")

        # 2. Validate dataset
        val_resp = test_client.post(
            "/v1/onboard/validate",
            headers={"X-API-Key": key},
        )
        assert val_resp.status_code == 200

        # 3. Confirm config
        candidate_cfg = val_resp.json()["candidate_config"]
        conf_resp = test_client.post(
            "/v1/onboard/confirm",
            json={"candidate_config": candidate_cfg},
            headers={"X-API-Key": key},
        )
        assert conf_resp.status_code == 200

        # 4. Run pipeline on S3
        tr_resp = test_client.post("/v1/onboard/train", headers={"X-API-Key": key})
        assert tr_resp.status_code == 202

        # 5. Wait for tournament completion
        start_t = time.time()
        final_status = None
        while time.time() - start_t < 30:
            st = test_client.get("/v1/onboard/status", headers={"X-API-Key": key}).json()
            if st.get("status") in ("completed", "complete"):
                final_status = st
                break
            time.sleep(0.3)

        assert final_status is not None
        assert final_status["ready"] is True
        assert s3_storage.exists(f"models/{tenant_id}/final_model.joblib")
        assert s3_storage.exists(f"data/processed/{tenant_id}/customers.csv")

    finally:
        TENANT_AUTH_MAPPING.pop(key, None)


def test_stalled_job_reporting(test_client: TestClient, monkeypatch):
    """Verify that jobs running longer than 15 minutes are reported as 'stalled'."""
    tenant_id = "stalled_tenant"
    key = "sk-stalled-test"
    TENANT_AUTH_MAPPING[key] = tenant_id
    storage = LocalStorage()

    try:
        # Create a status file with updated_at set to 16 minutes ago
        past_time = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
        status_payload = {
            "tenant_id": tenant_id,
            "status": "running",
            "stage": "training_content",
            "message": "Still training...",
            "updated_at": past_time,
        }
        storage.write_file(f"status/{tenant_id}.json", json.dumps(status_payload).encode("utf-8"))

        res = test_client.get("/v1/onboard/status", headers={"X-API-Key": key})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "stalled"
        assert data["ready"] is False
        assert "stalled" in data["error"].lower()

    finally:
        TENANT_AUTH_MAPPING.pop(key, None)
        _cleanup_tenant_files(tenant_id)


def test_multi_worker_model_cache_invalidation(monkeypatch):
    """Simulate two independent worker processes accessing the same storage.

    Verifies that Worker B automatically reloads the model when Worker A updates it,
    respecting the 30-second version marker check.
    """
    storage = LocalStorage()
    tenant_id = "cache_test_tenant"
    _cleanup_tenant_files(tenant_id)

    try:
        # 1. Worker A saves Version 1 of the model
        model_v1 = DummyModel("v1")
        model_path = f"models/{tenant_id}/final_model.joblib"
        save_model(model_v1, model_path, storage=storage)

        # 2. Worker B loads the model and caches it
        clear_model_cache()
        loaded_worker_b = get_model_for_tenant(tenant_id, storage=storage)
        assert loaded_worker_b.version == "v1"

        # 3. Worker A saves Version 2 of the model
        time.sleep(0.05)  # Ensure distinct timestamp/marker
        model_v2 = DummyModel("v2")
        save_model(model_v2, model_path, storage=storage)

        # 4. Immediate access on Worker B uses in-memory cache (< 30s)
        cached_immediate = get_model_for_tenant(tenant_id, storage=storage)
        assert cached_immediate.version == "v1"

        # 5. Fast-forward Worker B's last_checked time by 31 seconds
        MODEL_CACHE_METADATA[tenant_id]["last_checked"] -= 35.0

        # 6. Worker B checks version marker and reloads Version 2
        reloaded_worker_b = get_model_for_tenant(tenant_id, storage=storage)
        assert reloaded_worker_b.version == "v2"

    finally:
        clear_model_cache()
        _cleanup_tenant_files(tenant_id)


def test_startup_jwt_secret_enforcement(monkeypatch):
    """Verify that lifespan refuses to start in production without JWT_SECRET_KEY."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "")

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY must be set in production environment"):
        import asyncio
        async def run_startup():
            async with lifespan(app):
                pass
        asyncio.run(run_startup())
