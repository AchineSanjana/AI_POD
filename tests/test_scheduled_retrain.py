"""Tests for Amazon EventBridge scheduled model retraining workflow.

Verifies:
1. Calling the EventBridge target endpoint (POST /v1/retrain/scheduled):
   - For newly ready-to-train untrained tenants: kicks off their first training run.
   - For already-trained tenants: kicks off a retrain incorporating new interaction data.
   - For tenants with an active training run already in progress: avoids collision and skips cleanly.
2. Per-tenant summary report logging and persistence in status/scheduled_retrain_latest.json.
3. GET /v1/retrain/latest returns the audit log of the most recent scheduled retraining cycle.
4. Amazon EventBridge rule provisioning via boto3 events client (mocked with moto).
"""

from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

import boto3
from fastapi.testclient import TestClient
from moto import mock_aws
import pandas as pd
import pytest

from src.api.app import app
from src.api.auth import TENANT_AUTH_MAPPING
from src.api.onboarding import (
    _ACTIVE_TRAINING_THREADS,
    _save_training_status,
)
from src.api.recommendations import clear_model_cache
from src.integrations.aws.eventbridge import (
    get_retrain_eventbridge_rule,
    setup_retrain_eventbridge_rule,
)
from src.scheduler.retrain_orchestrator import run_scheduled_retraining
from src.storage import get_storage_backend
from src.utils.config import load_config, resolve_path


@pytest.fixture
def aws_env(monkeypatch):
    """Set standard AWS environment variables for moto tests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


@pytest.fixture
def client():
    clear_model_cache()
    _ACTIVE_TRAINING_THREADS.clear()
    with TestClient(app) as test_client:
        yield test_client
    clear_model_cache()
    _ACTIVE_TRAINING_THREADS.clear()


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


def test_eventbridge_scheduled_retrain_new_tenant_retrain_and_collision_prevention(client: TestClient):
    """Confirm EventBridge trigger call handles new-ready, already-trained, and in-progress tenants correctly."""
    storage = get_storage_backend()
    config = load_config()

    t_new_ready = "tenant_eb_new_ready"
    t_already_trained = "tenant_eb_trained"
    t_in_progress = "tenant_eb_running"
    t_below = "tenant_eb_below"

    api_key = "sk-eb-test-key"
    TENANT_AUTH_MAPPING[api_key] = "admin_tenant"

    all_test_tenants = [t_new_ready, t_already_trained, t_in_progress, t_below]

    try:
        for t in all_test_tenants:
            _cleanup_tenant(t, storage=storage)

        # -------------------------------------------------------------------
        # 1. Setup Tenant A: New tenant marked ready_to_train (never trained)
        # -------------------------------------------------------------------
        _save_training_status(
            tenant_id=t_new_ready,
            status_val="ready_to_train",
            message="Tenant reached thresholds and is ready to train.",
            storage=storage,
        )
        # Seed processed data for tenant A
        cust_a = pd.DataFrame([{"customer_id": f"c_{i}"} for i in range(10)])
        prod_a = pd.DataFrame([{"product_id": f"p_{i}", "product_name": f"Prod {i}", "category": "Core"} for i in range(5)])
        int_a = pd.DataFrame([{"customer_id": f"c_{i % 10}", "product_id": f"p_{i % 5}"} for i in range(20)])
        storage.write_file(f"data/processed/{t_new_ready}/customers.csv", cust_a.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{t_new_ready}/products.csv", prod_a.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{t_new_ready}/interactions.csv", int_a.to_csv(index=False).encode("utf-8"))

        # -------------------------------------------------------------------
        # 2. Setup Tenant B: Already trained tenant with new interactions arrived
        # -------------------------------------------------------------------
        # Create dummy existing model in storage
        storage.write_file(f"models/{t_already_trained}/final_model.joblib", b"DUMMY_MODEL_BYTES")
        _save_training_status(
            tenant_id=t_already_trained,
            status_val="complete",
            message="Model successfully trained and saved.",
            storage=storage,
            model_path=f"models/{t_already_trained}/final_model.joblib",
        )
        cust_b = pd.DataFrame([{"customer_id": f"cb_{i}"} for i in range(10)])
        prod_b = pd.DataFrame([{"product_id": f"pb_{i}", "product_name": f"Item {i}", "category": "Add-on"} for i in range(5)])
        int_b = pd.DataFrame([{"customer_id": f"cb_{i % 10}", "product_id": f"pb_{i % 5}"} for i in range(25)])
        storage.write_file(f"data/processed/{t_already_trained}/customers.csv", cust_b.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{t_already_trained}/products.csv", prod_b.to_csv(index=False).encode("utf-8"))
        storage.write_file(f"data/processed/{t_already_trained}/interactions.csv", int_b.to_csv(index=False).encode("utf-8"))

        # -------------------------------------------------------------------
        # 3. Setup Tenant C: Training ALREADY in progress (queued/running)
        # -------------------------------------------------------------------
        _save_training_status(
            tenant_id=t_in_progress,
            status_val="running",
            message="Training job is currently running.",
            storage=storage,
        )
        # Simulate active worker thread
        mock_thread = threading.Thread(target=time.sleep, args=(5,), daemon=True)
        mock_thread.start()
        _ACTIVE_TRAINING_THREADS[t_in_progress] = mock_thread

        # -------------------------------------------------------------------
        # 4. Setup Tenant D: Untrained but NOT marked ready to train (below threshold)
        # -------------------------------------------------------------------
        _save_training_status(
            tenant_id=t_below,
            status_val="needs_configuration",
            message="Dataset uploaded, awaiting configuration.",
            storage=storage,
        )

        # -------------------------------------------------------------------
        # 5. Invoke EventBridge Target Endpoint: POST /v1/retrain/scheduled
        # -------------------------------------------------------------------
        resp = client.post(
            "/v1/retrain/scheduled",
            json={"wait_for_completion": True, "timeout_seconds": 15.0},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "ok"
        assert "timestamp" in data
        assert data["total_tenants_checked"] >= 3

        summary_map = {s["tenant_id"]: s for s in data["summaries"]}

        # Verify Tenant A (new ready): first_training action was triggered
        assert t_new_ready in summary_map
        sum_a = summary_map[t_new_ready]
        assert sum_a["tenant_type"] == "new_ready"
        assert sum_a["action"] == "first_training"
        assert sum_a["status"] == "queued"

        # Verify Tenant B (already trained): retrain action was triggered
        assert t_already_trained in summary_map
        sum_b = summary_map[t_already_trained]
        assert sum_b["tenant_type"] == "already_trained"
        assert sum_b["action"] == "retrain"
        assert sum_b["status"] == "queued"

        # Verify Tenant C (in progress): skipped cleanly to prevent collision!
        assert t_in_progress in summary_map
        sum_c = summary_map[t_in_progress]
        assert sum_c["tenant_type"] == "in_progress"
        assert sum_c["action"] == "skipped"
        assert sum_c["status"] == "skipped"
        assert "already in progress" in sum_c["reason"].lower()

        # Verify Tenant D (untrained, not ready): skipped
        assert t_below in summary_map
        sum_d = summary_map[t_below]
        assert sum_d["tenant_type"] == "below_threshold"
        assert sum_d["action"] == "skipped"

        # -------------------------------------------------------------------
        # 6. Verify audit persistence and GET /v1/retrain/latest
        # -------------------------------------------------------------------
        assert storage.exists("status/scheduled_retrain_latest.json")
        latest_resp = client.get("/v1/retrain/latest", headers={"X-API-Key": api_key})
        assert latest_resp.status_code == 200
        latest_data = latest_resp.json()
        assert latest_data["timestamp"] == data["timestamp"]
        assert len(latest_data["summaries"]) == len(data["summaries"])

    finally:
        TENANT_AUTH_MAPPING.pop(api_key, None)
        for t in all_test_tenants:
            _cleanup_tenant(t, storage=storage)
        _ACTIVE_TRAINING_THREADS.clear()


@mock_aws
def test_eventbridge_rule_setup_boto3(aws_env):
    """Verify provisioning and querying Amazon EventBridge scheduled rule using boto3."""
    rule_name = "ai-pod-nightly-retrain-test"
    schedule = "cron(0 2 * * ? *)"

    # 1. Provision rule
    result = setup_retrain_eventbridge_rule(
        rule_name=rule_name,
        schedule_expression=schedule,
        target_endpoint_url="https://api.example.com/v1/retrain/scheduled",
        region_name="us-east-1",
        state="ENABLED",
    )
    assert result["rule_name"] == rule_name
    assert result["schedule_expression"] == schedule
    assert result["state"] == "ENABLED"
    assert "rule_arn" in result
    assert result["rule_arn"] is not None

    # 2. Inspect rule via get_retrain_eventbridge_rule
    rule_info = get_retrain_eventbridge_rule(rule_name=rule_name, region_name="us-east-1")
    assert rule_info is not None
    assert rule_info["rule_name"] == rule_name
    assert rule_info["schedule_expression"] == schedule
    assert rule_info["state"] == "ENABLED"


def test_scheduler_retrain_direct_orchestrator():
    """Verify run_scheduled_retraining executes and logs cleanly when called directly."""
    storage = get_storage_backend()
    report = run_scheduled_retraining(storage=storage, wait_for_completion=False)
    assert isinstance(report, dict)
    assert report["status"] == "ok"
    assert "summaries" in report
    assert isinstance(report["summaries"], list)
