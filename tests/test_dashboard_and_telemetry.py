"""Comprehensive tests for Dashboard endpoints and Telemetry subsystem.

Verifies:
1. Telemetry buffering and non-blocking flush (Local and S3).
2. Multi-worker collision safety (unique timestamp-pid-random filenames).
3. Test traffic exclusion (X-AIPOD-Source: wizard-test excluded from metrics).
4. Empty tenant responses (honest zeros and nulls, no 500 errors).
5. Strict tenant isolation (cross-tenant metrics cannot leak).
6. Retention cleanup of expired telemetry files.
7. Admin auth enforcement on all dashboard endpoints.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
import json
import os
import shutil
import tempfile
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.accounts.session import create_session_token
from src.accounts.storage import save_account_record
from src.api.app import app
from src.api.auth import TENANT_KEY_RECORDS, load_tenant_auth
from src.storage.local_storage import LocalStorage
from src.storage.s3_storage import S3Storage
from src.telemetry.collector import (
    clear_telemetry_buffer,
    flush_telemetry,
    record_event,
    record_recommendation,
)
from src.telemetry.reader import (
    clear_telemetry_cache,
    get_tenant_events,
    get_tenant_telemetry,
)
from src.telemetry.retention import cleanup_old_telemetry


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure in-memory buffers and caches are reset before and after each test."""
    clear_telemetry_buffer()
    clear_telemetry_cache()
    load_tenant_auth()
    yield
    clear_telemetry_buffer()
    clear_telemetry_cache()


@pytest.fixture
def client():
    return TestClient(app)


def test_telemetry_buffering_and_flush(tmp_path):
    """Verify records accumulate in memory and flush to unique JSONL part files."""
    storage = LocalStorage(base_dir=str(tmp_path))
    tenant = "test_buffering_tenant"

    # Record recommendations
    record_recommendation(
        tenant_id=tenant,
        customer_id="cust_1",
        top_n=5,
        fallback=False,
        reason=None,
        latency_ms=12.5,
        source="live",
        recommended_products=["prod_a", "prod_b"],
    )
    record_recommendation(
        tenant_id=tenant,
        customer_id="cust_2",
        top_n=3,
        fallback=True,
        reason="unknown_customer",
        latency_ms=8.2,
        source="live",
        recommended_products=["prod_pop1"],
    )

    # Record client interaction event
    record_event(
        tenant_id=tenant,
        event_type="view",
        product_id="prod_a",
        session_id="sess_123",
        customer_id="cust_1",
    )

    # Flush buffer to storage
    flushed_count = flush_telemetry(storage=storage)
    assert flushed_count == 3

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    part_files = storage.list_files(f"data/telemetry/{tenant}/{today_str}/")
    assert len(part_files) == 1
    part_path = part_files[0]
    assert part_path.startswith(f"data/telemetry/{tenant}/")
    assert part_path.endswith(".jsonl")

    # Read part file content
    content = storage.read_file(part_path).decode("utf-8")
    lines = [json.loads(line) for line in content.splitlines() if line.strip()]
    assert len(lines) == 3

    types = [line["type"] for line in lines]
    assert types == ["recommendation", "recommendation", "event"]

    # In-memory buffer must be empty after flush
    assert flush_telemetry(storage=storage) == 0


def test_telemetry_mock_s3_flush():
    """Verify telemetry flushes cleanly via S3Storage without append operations."""
    mock_s3_client = MagicMock()
    storage = S3Storage(bucket_name="mock-aipod-bucket", prefix="stage", s3_client=mock_s3_client)
    tenant = "test_s3_tenant"

    record_recommendation(
        tenant_id=tenant,
        customer_id="s3_cust",
        top_n=5,
        fallback=False,
        reason=None,
        latency_ms=15.0,
        source="live",
        recommended_products=["s3_prod"],
    )

    flushed = flush_telemetry(storage=storage)
    assert flushed == 1
    assert mock_s3_client.put_object.called

    call_kwargs = mock_s3_client.put_object.call_args[1]
    assert call_kwargs["Bucket"] == "mock-aipod-bucket"
    assert call_kwargs["Key"].startswith(f"stage/data/telemetry/{tenant}/")
    assert b"s3_cust" in call_kwargs["Body"]


def test_concurrent_multiworker_flush_collision_safety(tmp_path):
    """Simulate concurrent threads/workers flushing telemetry simultaneously."""
    storage = LocalStorage(base_dir=str(tmp_path))
    tenant = "concurrent_tenant"

    def worker_task(worker_id: int):
        for i in range(5):
            record_recommendation(
                tenant_id=tenant,
                customer_id=f"worker_{worker_id}_cust_{i}",
                top_n=3,
                fallback=False,
                reason=None,
                latency_ms=10.0,
                source="live",
                recommended_products=[f"prod_{worker_id}_{i}"],
            )
        return flush_telemetry(storage=storage)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker_task, wid) for wid in range(10)]
        total_flushed = sum(f.result() for f in concurrent.futures.as_completed(futures))

    assert total_flushed == 50

    # Ensure all part file paths are strictly unique
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    part_files = storage.list_files(f"data/telemetry/{tenant}/{today_str}/")
    assert len(part_files) >= 1
    assert len(part_files) == len(set(part_files))

    # Read back all records and verify total count
    total_records = 0
    for pf in part_files:
        lines = storage.read_file(pf).decode("utf-8").splitlines()
        total_records += sum(1 for line in lines if line.strip())

    assert total_records == 50


def test_test_traffic_exclusion(client, tmp_path):
    """Verify X-AIPOD-Source: wizard-test is flagged source='test' and excluded from metrics."""
    tenant = "test_traffic_iso_tenant"
    sk_key = "sk-traffic-iso-sk"

    from src.api.auth import TENANT_AUTH_MAPPING, TENANT_KEY_RECORDS
    TENANT_AUTH_MAPPING[sk_key] = tenant
    TENANT_KEY_RECORDS[sk_key] = {"tenant_id": tenant, "key_type": "private", "created_at": None}

    clear_telemetry_buffer()
    clear_telemetry_cache()

    # 1. Send test recommendation with wizard-test header
    resp_test = client.get(
        "/v1/recommendations?customer_id=user_iso_99&top_n=5",
        headers={"X-API-Key": sk_key, "X-AIPOD-Source": "wizard-test"},
    )
    assert resp_test.status_code == 200

    # 2. Check telemetry overview before live request: requests_today must be 0
    resp_overview_1 = client.get(
        "/v1/dashboard/overview",
        headers={"X-API-Key": sk_key},
    )
    assert resp_overview_1.status_code == 200
    assert resp_overview_1.json()["requests_today"] == 0

    # 3. Send normal live recommendation
    resp_live = client.get(
        "/v1/recommendations?customer_id=user_iso_99&top_n=5",
        headers={"X-API-Key": sk_key},
    )
    assert resp_live.status_code == 200

    clear_telemetry_cache()

    # 4. Overview must now show exactly 1 live request
    resp_overview_2 = client.get(
        "/v1/dashboard/overview",
        headers={"X-API-Key": sk_key},
    )
    assert resp_overview_2.status_code == 200
    assert resp_overview_2.json()["requests_today"] == 1


def test_dashboard_endpoints_empty_tenant(client):
    """Verify empty tenant returns valid schemas with 0s and nulls without 500 error."""
    tenant = "empty_tenant_xyz"
    acc_id = "acc_empty_123"
    save_account_record(
        acc_id,
        {
            "account_id": acc_id,
            "tenant_id": tenant,
            "email": "empty@tenant.com",
            "email_verified": True,
        },
    )
    token = create_session_token(
        account_id=acc_id,
        tenant_id=tenant,
        email="empty@tenant.com",
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET /v1/dashboard/overview
    resp_ov = client.get("/v1/dashboard/overview", headers=headers)
    assert resp_ov.status_code == 200
    ov_data = resp_ov.json()
    assert ov_data["tenant_id"] == tenant
    assert ov_data["status"] == "not_started"
    assert ov_data["ready"] is False
    assert ov_data["winning_model"] is None
    assert ov_data["winner_key"] is None
    assert ov_data["metrics"] is None
    assert ov_data["dataset_stats"] is None
    assert ov_data["requests_today"] == 0
    assert ov_data["active_key_count"] == 0
    assert ov_data["last_trained"] is None

    # 2. GET /v1/dashboard/models
    resp_models = client.get("/v1/dashboard/models", headers=headers)
    assert resp_models.status_code == 200
    models_data = resp_models.json()
    assert models_data["tenant_id"] == tenant
    assert models_data["status"] == "not_started"
    assert models_data["winner_key"] is None
    assert len(models_data["models"]) == 4
    for m in models_data["models"]:
        assert m["status"] == "not_started"
        assert m["ndcg"] is None
        assert m["precision"] is None
        assert m["recall"] is None
        assert m["is_winner"] is False

    # 3. GET /v1/dashboard/analytics
    resp_analytics = client.get("/v1/dashboard/analytics?days=7", headers=headers)
    assert resp_analytics.status_code == 200
    analytics_data = resp_analytics.json()
    assert analytics_data["tenant_id"] == tenant
    assert analytics_data["total_events"] == 0
    assert analytics_data["total_recommendations"] == 0
    assert analytics_data["fallback_rate"] is None
    assert analytics_data["ctr"] is None
    assert len(analytics_data["events_by_day"]) == 7
    assert analytics_data["top_products"] == []

    # 4. GET /v1/dashboard/events
    resp_events = client.get("/v1/dashboard/events?limit=20", headers=headers)
    assert resp_events.status_code == 200
    events_data = resp_events.json()
    assert events_data["tenant_id"] == tenant
    assert events_data["events"] == []


def test_tenant_isolation(client):
    """Verify Tenant A's telemetry and metrics are completely hidden from Tenant B."""
    tenant_a = "tenant_iso_a"
    tenant_b = "tenant_iso_b"

    save_account_record(
        "acc_a_iso",
        {"account_id": "acc_a_iso", "tenant_id": tenant_a, "email": "a@iso.com", "email_verified": True},
    )
    save_account_record(
        "acc_b_iso",
        {"account_id": "acc_b_iso", "tenant_id": tenant_b, "email": "b@iso.com", "email_verified": True},
    )

    token_a = create_session_token(account_id="acc_a_iso", tenant_id=tenant_a, email="a@iso.com")
    token_b = create_session_token(account_id="acc_b_iso", tenant_id=tenant_b, email="b@iso.com")

    # Record data exclusively for Tenant A
    record_recommendation(
        tenant_id=tenant_a,
        customer_id="cust_a_1",
        top_n=5,
        fallback=False,
        reason=None,
        latency_ms=10.0,
        source="live",
        recommended_products=["prod_a_100"],
    )
    record_event(
        tenant_id=tenant_a,
        event_type="purchase",
        product_id="prod_a_100",
        session_id="sess_a",
        customer_id="cust_a_1",
    )

    clear_telemetry_cache()

    # Query Tenant A
    resp_a_ov = client.get("/v1/dashboard/overview", headers={"Authorization": f"Bearer {token_a}"})
    assert resp_a_ov.status_code == 200
    assert resp_a_ov.json()["requests_today"] == 1

    resp_a_ev = client.get("/v1/dashboard/events", headers={"Authorization": f"Bearer {token_a}"})
    assert resp_a_ev.status_code == 200
    assert len(resp_a_ev.json()["events"]) == 1
    assert resp_a_ev.json()["events"][0]["product_id"] == "prod_a_100"

    # Query Tenant B: must see ZERO events and ZERO requests
    resp_b_ov = client.get("/v1/dashboard/overview", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b_ov.status_code == 200
    assert resp_b_ov.json()["requests_today"] == 0

    resp_b_ev = client.get("/v1/dashboard/events", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b_ev.status_code == 200
    assert len(resp_b_ev.json()["events"]) == 0


def test_retention_cleanup(tmp_path):
    """Verify cleanup_old_telemetry purges part files older than retention_days."""
    storage = LocalStorage(base_dir=str(tmp_path))
    tenant = "retention_tenant"

    old_date = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d")
    recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")

    old_file = f"data/telemetry/{tenant}/{old_date}/part-old-001.jsonl"
    recent_file = f"data/telemetry/{tenant}/{recent_date}/part-recent-002.jsonl"

    storage.write_file(old_file, b'{"type":"event"}\n')
    storage.write_file(recent_file, b'{"type":"event"}\n')

    assert storage.exists(old_file)
    assert storage.exists(recent_file)

    deleted = cleanup_old_telemetry(retention_days=30, storage=storage)
    assert deleted == 1
    assert not storage.exists(old_file)
    assert storage.exists(recent_file)


def test_dashboard_auth_enforcement(client):
    """Verify all dashboard endpoints enforce get_tenant_for_admin_action."""
    # 1. No auth -> 401
    assert client.get("/v1/dashboard/overview").status_code == 401
    assert client.get("/v1/dashboard/models").status_code == 401
    assert client.get("/v1/dashboard/analytics").status_code == 401
    assert client.get("/v1/dashboard/events").status_code == 401

    # 2. Public pk- key -> 403 Forbidden
    pk_headers = {"X-API-Key": "pk-telco-xxxx"}
    assert client.get("/v1/dashboard/overview", headers=pk_headers).status_code == 403
    assert client.get("/v1/dashboard/models", headers=pk_headers).status_code == 403
    assert client.get("/v1/dashboard/analytics", headers=pk_headers).status_code == 403
    assert client.get("/v1/dashboard/events", headers=pk_headers).status_code == 403

    # 3. Private sk- key -> 200 OK
    sk_headers = {"X-API-Key": "sk-telco-xxxx"}
    assert client.get("/v1/dashboard/overview", headers=sk_headers).status_code == 200
    assert client.get("/v1/dashboard/models", headers=sk_headers).status_code == 200
    assert client.get("/v1/dashboard/analytics", headers=sk_headers).status_code == 200
    assert client.get("/v1/dashboard/events", headers=sk_headers).status_code == 200


def test_overview_never_modifies_running_status_file(client, tmp_path):
    """Verify GET /v1/dashboard/overview NEVER writes to or mutates status/{tenant_id}.json.

    Starts with a status file whose status is 'running', calls /overview,
    and asserts the status file is byte-for-byte unchanged.
    """
    from src.storage import get_storage_backend
    from src.utils.config import load_config
    from src.api.auth import TENANT_AUTH_MAPPING, TENANT_KEY_RECORDS

    tenant = "test_running_tenant_immutable"
    sk_key = "sk-running-test-sk"
    TENANT_AUTH_MAPPING[sk_key] = tenant
    TENANT_KEY_RECORDS[sk_key] = {"tenant_id": tenant, "key_type": "private", "created_at": None}

    cfg = load_config()
    storage = get_storage_backend(cfg)

    # Prepare status file with status="running" and NO dataset stats
    status_content = (
        b'{\n'
        b'  "tenant_id": "test_running_tenant_immutable",\n'
        b'  "status": "running",\n'
        b'  "stage": "training_models",\n'
        b'  "message": "Tournament in progress..."\n'
        b'}\n'
    )
    status_path = f"status/{tenant}.json"
    storage.write_file(status_path, status_content)

    # Verify initial bytes
    assert storage.read_file(status_path) == status_content

    # Call GET /v1/dashboard/overview
    resp = client.get("/v1/dashboard/overview", headers={"X-API-Key": sk_key})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"

    # Assert status file is byte-for-byte completely unchanged
    bytes_after = storage.read_file(status_path)
    assert bytes_after == status_content

    # Cleanup
    try:
        storage.delete_file(status_path)
        stats_cache = f"status/{tenant}_dataset_stats.json"
        if storage.exists(stats_cache):
            storage.delete_file(stats_cache)
    except Exception:
        pass
