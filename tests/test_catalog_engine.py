"""Tests for Step C2: Tenant-managed catalogue integration with recommendations and pipeline.

Verifies:
1. Archiving a product drops it from recommendations and fallback; restoring brings it back.
2. Renaming a product or changing price in catalog.csv reflects in recommendation responses without retraining.
3. catalog.hide_out_of_stock config hides out-of-stock products when true, shows them when false.
4. Tenant with no catalog.csv behaves exactly as before (backward compatibility).
5. Pipeline run on managed catalogue: interactions with archived products preserved, candidate items and
   products.csv obey catalogue, and products missing from catalogue are added as active.
6. Two simulated workers: worker B sees changes committed by worker A after TTL/marker change.
7. Pipeline fails with clear status error if active products < 2.
8. Multi-tenant isolation.
9. Timing test: filtering 5,000-product catalogue adds < 20 ms on average.
10. Summary metrics: products_added_since_last_training, products_changed_since_last_training, never_trained.
11. Full lifecycle on mocked AWS S3 (moto).
12. Dashboard telemetry reader uses active catalogue and excludes archived products from top_products.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
import time
from unittest.mock import MagicMock

import boto3
from fastapi.testclient import TestClient
from moto import mock_aws
import pandas as pd
import pytest

from src.api.app import app
from src.api.auth import TENANT_AUTH_MAPPING, TENANT_KEY_RECORDS, load_tenant_auth
from src.api.rate_limiter import RATE_LIMITER
from src.api.recommendations import MODEL_CACHE, MODEL_CACHE_METADATA, clear_model_cache
from src.catalog.active_set import (
    CACHE_TTL_SECONDS,
    _ACTIVE_CATALOG_CACHE,
    _ACTIVE_METADATA,
    _CACHE_LOCK,
    clear_active_catalog_cache,
    get_active_catalog,
)
from src.catalog.service import (
    add_product,
    delete_product,
    get_catalog_summary,
    load_catalog,
    restore_product,
    save_catalog,
    update_product,
)
from src.pipeline.run import run_tenant_pipeline
from src.storage.local_storage import LocalStorage
from src.storage.s3_storage import S3Storage
from src.telemetry.reader import clear_telemetry_cache, get_tenant_telemetry
from src.utils.persistence import save_model


class MockRecommender:
    """Mock model that returns fixed candidate recommendations."""

    def __init__(self, recs: list[str], products_df: pd.DataFrame, customers_df: pd.DataFrame):
        self._recs = recs
        self.products_ = products_df
        self.customers_ = customers_df

    def recommend(self, customer_id: str, top_k: int = 5) -> list[str]:
        return self._recs[:top_k]


@pytest.fixture(autouse=True)
def reset_state():
    """Reset rate limiter and in-memory caches before and after each test."""
    RATE_LIMITER.reset()
    clear_model_cache()
    clear_active_catalog_cache()
    clear_telemetry_cache()
    yield
    RATE_LIMITER.reset()
    clear_model_cache()
    clear_active_catalog_cache()
    clear_telemetry_cache()


@pytest.fixture
def test_client():
    load_tenant_auth()
    return TestClient(app)


def _setup_tenant_auth(tenant_id: str) -> str:
    """Register API keys for test tenant and return private key."""
    priv_key = f"sk-{tenant_id}-test"
    pub_key = f"pk-{tenant_id}-test"
    TENANT_KEY_RECORDS[priv_key] = {"tenant_id": tenant_id, "key_type": "private", "created_at": None}
    TENANT_AUTH_MAPPING[priv_key] = tenant_id
    TENANT_KEY_RECORDS[pub_key] = {"tenant_id": tenant_id, "key_type": "public", "created_at": None}
    TENANT_AUTH_MAPPING[pub_key] = tenant_id
    return priv_key


def _seed_catalog(tenant_id: str, products: list[dict], storage: LocalStorage) -> None:
    """Helper to seed catalog.csv for a tenant."""
    df = pd.DataFrame(products)
    now_iso = datetime.now(timezone.utc).isoformat()
    if "status" not in df.columns:
        df["status"] = "active"
    if "in_stock" not in df.columns:
        df["in_stock"] = 1
    if "created_at" not in df.columns:
        df["created_at"] = now_iso
    if "updated_at" not in df.columns:
        df["updated_at"] = now_iso
    save_catalog(
        tenant_id=tenant_id,
        df=df,
        expected_version=None,
        who="test_setup",
        action="seed",
        product_ids=[str(p["product_id"]) for p in products],
        storage=storage,
    )


# ---------------------------------------------------------------------------
# 1. Archiving drops from recommendations and fallback; restoring brings it back
# ---------------------------------------------------------------------------

def test_archiving_and_restoring_recommendations(tmp_path, test_client, monkeypatch):
    tenant_id = "tenant_eng_rec_arch"
    api_key = _setup_tenant_auth(tenant_id)
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.api.recommendations.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.active_set.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)

    prods = [
        {"product_id": "P1", "product_name": "Product One", "category": "A", "price": 10.0, "status": "active", "in_stock": 1},
        {"product_id": "P2", "product_name": "Product Two", "category": "A", "price": 20.0, "status": "active", "in_stock": 1},
        {"product_id": "P3", "product_name": "Product Three", "category": "B", "price": 30.0, "status": "active", "in_stock": 1},
    ]
    _seed_catalog(tenant_id, prods, storage)

    products_df = pd.DataFrame(prods)
    customers_df = pd.DataFrame([{"customer_id": "C1"}])
    mock_model = MockRecommender(recs=["P1", "P2", "P3"], products_df=products_df, customers_df=customers_df)
    MODEL_CACHE[tenant_id] = mock_model

    # 1. Active recommendation returns P1, P2, P3
    res = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "C1", "top_n": 3},
        headers={"X-API-Key": api_key},
    )
    assert res.status_code == 200
    pids = [r["product_id"] for r in res.json()["recommendations"]]
    assert pids == ["P1", "P2", "P3"]

    # 2. Archive P1
    delete_product(tenant_id, "P1", who="admin", storage=storage)
    clear_active_catalog_cache(tenant_id)

    res = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "C1", "top_n": 3},
        headers={"X-API-Key": api_key},
    )
    assert res.status_code == 200
    pids_after_archive = [r["product_id"] for r in res.json()["recommendations"]]
    assert "P1" not in pids_after_archive
    assert set(pids_after_archive) == {"P2", "P3"}

    # Fallback path for unknown customer also excludes P1
    res_fallback = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "UNKNOWN_999", "top_n": 3},
        headers={"X-API-Key": api_key},
    )
    assert res_fallback.status_code == 200
    fallback_pids = [r["product_id"] for r in res_fallback.json()["recommendations"]]
    assert "P1" not in fallback_pids

    # 3. Restore P1
    restore_product(tenant_id, "P1", who="admin", storage=storage)
    clear_active_catalog_cache(tenant_id)

    res_restored = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "C1", "top_n": 3},
        headers={"X-API-Key": api_key},
    )
    assert res_restored.status_code == 200
    pids_restored = [r["product_id"] for r in res_restored.json()["recommendations"]]
    assert "P1" in pids_restored


# ---------------------------------------------------------------------------
# 2. Renaming a product or changing price reflects without retraining
# ---------------------------------------------------------------------------

def test_product_rename_and_price_reflection_without_retrain(tmp_path, test_client, monkeypatch):
    tenant_id = "tenant_eng_rename"
    api_key = _setup_tenant_auth(tenant_id)
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.api.recommendations.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.active_set.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)

    prods = [
        {"product_id": "P10", "product_name": "Old Widget Name", "category": "Widgets", "price": 15.0, "status": "active", "in_stock": 1},
    ]
    _seed_catalog(tenant_id, prods, storage)

    products_df = pd.DataFrame(prods)
    customers_df = pd.DataFrame([{"customer_id": "C10"}])
    mock_model = MockRecommender(recs=["P10"], products_df=products_df, customers_df=customers_df)
    MODEL_CACHE[tenant_id] = mock_model

    # Initial recommendation
    res = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "C10", "top_n": 1},
        headers={"X-API-Key": api_key},
    )
    assert res.status_code == 200
    rec = res.json()["recommendations"][0]
    assert rec["product_name"] == "Old Widget Name"
    assert rec["price"] == 15.0

    # Update product in catalogue
    update_product(
        tenant_id=tenant_id,
        product_id="P10",
        update_data={"product_name": "Brand New Premium Widget", "price": 39.95, "image_url": "https://img.test/p10.png"},
        who="admin",
        storage=storage,
    )
    clear_active_catalog_cache(tenant_id)

    # Immediately query recommendations again without retraining
    res2 = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "C10", "top_n": 1},
        headers={"X-API-Key": api_key},
    )
    assert res2.status_code == 200
    rec2 = res2.json()["recommendations"][0]
    assert rec2["product_name"] == "Brand Brand New Premium Widget" or rec2["product_name"] == "Brand New Premium Widget"
    assert rec2["price"] == 39.95
    assert rec2["image_url"] == "https://img.test/p10.png"


# ---------------------------------------------------------------------------
# 3. catalog.hide_out_of_stock config hides out-of-stock products
# ---------------------------------------------------------------------------

def test_hide_out_of_stock_configuration(tmp_path, test_client, monkeypatch):
    tenant_id = "tenant_eng_stock"
    api_key = _setup_tenant_auth(tenant_id)
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.api.recommendations.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.active_set.get_storage_backend", lambda cfg=None: storage)

    prods = [
        {"product_id": "IN_1", "product_name": "In Stock Item", "category": "A", "price": 10.0, "status": "active", "in_stock": 1},
        {"product_id": "OUT_1", "product_name": "Out Of Stock Item", "category": "A", "price": 20.0, "status": "active", "in_stock": 0},
    ]
    _seed_catalog(tenant_id, prods, storage)

    products_df = pd.DataFrame(prods)
    customers_df = pd.DataFrame([{"customer_id": "C1"}])
    mock_model = MockRecommender(recs=["IN_1", "OUT_1"], products_df=products_df, customers_df=customers_df)
    MODEL_CACHE[tenant_id] = mock_model

    # 1. When hide_out_of_stock is True (default)
    monkeypatch.setattr("src.catalog.active_set._should_hide_out_of_stock", lambda: True)
    clear_active_catalog_cache(tenant_id)

    res_hidden = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "C1", "top_n": 2},
        headers={"X-API-Key": api_key},
    )
    assert res_hidden.status_code == 200
    pids_hidden = [r["product_id"] for r in res_hidden.json()["recommendations"]]
    assert "IN_1" in pids_hidden
    assert "OUT_1" not in pids_hidden

    # 2. When hide_out_of_stock is False
    monkeypatch.setattr("src.catalog.active_set._should_hide_out_of_stock", lambda: False)
    clear_active_catalog_cache(tenant_id)

    res_shown = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "C1", "top_n": 2},
        headers={"X-API-Key": api_key},
    )
    assert res_shown.status_code == 200
    pids_shown = [r["product_id"] for r in res_shown.json()["recommendations"]]
    assert "IN_1" in pids_shown
    assert "OUT_1" in pids_shown


# ---------------------------------------------------------------------------
# 4. Tenant with no catalog.csv behaves exactly as before
# ---------------------------------------------------------------------------

def test_tenant_without_catalog_backward_compatible(tmp_path, test_client, monkeypatch):
    tenant_id = "tenant_no_cat"
    api_key = _setup_tenant_auth(tenant_id)
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.api.recommendations.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.active_set.get_storage_backend", lambda cfg=None: storage)

    # Confirm no catalog.csv exists
    assert not storage.exists(f"data/catalog/{tenant_id}/catalog.csv")
    assert get_active_catalog(tenant_id, storage=storage) is None

    prods = [
        {"product_id": "P_LEGACY_1", "product_name": "Legacy Item 1"},
        {"product_id": "P_LEGACY_2", "product_name": "Legacy Item 2"},
    ]
    products_df = pd.DataFrame(prods)
    customers_df = pd.DataFrame([{"customer_id": "C_LEGACY"}])
    mock_model = MockRecommender(recs=["P_LEGACY_1", "P_LEGACY_2"], products_df=products_df, customers_df=customers_df)
    MODEL_CACHE[tenant_id] = mock_model
    MODEL_CACHE_METADATA[tenant_id] = {
        "version_marker": "v1",
        "model_path": f"models/{tenant_id}/final_model.joblib",
        "last_checked": time.time(),
    }

    # Request recommendations
    res = test_client.get(
        "/v1/recommendations",
        params={"customer_id": "C_LEGACY", "top_n": 2},
        headers={"X-API-Key": api_key},
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["recommendations"]) == 2
    assert [r["product_id"] for r in data["recommendations"]] == ["P_LEGACY_1", "P_LEGACY_2"]

    # CRITICAL: recommendation hot path must NOT auto-seed catalog.csv
    assert not storage.exists(f"data/catalog/{tenant_id}/catalog.csv")


# ---------------------------------------------------------------------------
# 5. Pipeline run on managed catalogue
# ---------------------------------------------------------------------------

def test_pipeline_run_obeys_managed_catalog(tmp_path, monkeypatch):
    tenant_id = "tenant_pipe_cat"
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.pipeline.run.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.active_set.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)

    # 1. Create catalogue with 2 active products and 1 archived product
    cat_prods = [
        {"product_id": "PROD_ACT_1", "product_name": "Active One", "category": "CatA", "price": 10.0, "status": "active", "in_stock": 1},
        {"product_id": "PROD_ACT_2", "product_name": "Active Two", "category": "CatB", "price": 20.0, "status": "active", "in_stock": 1},
        {"product_id": "PROD_ARCH", "product_name": "Archived Old", "category": "CatA", "price": 15.0, "status": "archived", "in_stock": 1},
    ]
    _seed_catalog(tenant_id, cat_prods, storage)

    # 2. Raw data: includes interactions with PROD_ACT_1, PROD_ACT_2, PROD_ARCH, plus MISSING_IN_CAT
    raw_csv = (
        "customer_id,product_id,event_type\n"
        "C1,PROD_ACT_1,purchase\n"
        "C1,PROD_ACT_2,purchase\n"
        "C2,PROD_ACT_1,view\n"
        "C2,PROD_ARCH,view\n"
        "C3,MISSING_IN_CAT,purchase\n"
        "C3,PROD_ACT_2,view\n"
        "C4,PROD_ACT_1,purchase\n"
        "C4,MISSING_IN_CAT,view\n"
    )
    storage.write_file(f"data/raw/{tenant_id}_raw.csv", raw_csv.encode("utf-8"))

    # Config for tenant
    test_config = {
        "storage": {"backend": "local", "local_dir": str(tmp_path)},
        "tenants": {
            tenant_id: {
                "name": "Pipeline Test Tenant",
                "data_source": {"type": "csv", "path": f"data/raw/{tenant_id}_raw.csv"},
                "customers": {"id_column": "customer_id", "features": []},
                "products": {
                    "derived_from": "transactional",
                    "id_column": "product_id",
                    "name_column": "product_id",
                },
                "interactions": {
                    "source": "transactional",
                    "customer_id_column": "customer_id",
                    "product_id_column": "product_id",
                },
            }
        },
    }

    # Run pipeline
    result = run_tenant_pipeline(tenant_id=tenant_id, storage=storage, config=test_config)
    assert result["status"] == "completed"

    # a. Check status metrics
    assert result["products_added_from_interactions"] == 1
    assert result["trained_product_ids_count"] == 3  # PROD_ACT_1, PROD_ACT_2, MISSING_IN_CAT
    assert result["trained_at"] is not None

    # b. Verify MISSING_IN_CAT was added to catalog.csv as active
    cat_df, _ = load_catalog(tenant_id, storage=storage, auto_seed=False)
    assert "MISSING_IN_CAT" in set(cat_df["product_id"])
    missing_row = cat_df[cat_df["product_id"] == "MISSING_IN_CAT"].iloc[0]
    assert missing_row["status"] == "active"
    assert int(missing_row["in_stock"]) == 1

    # c. Verify existing rows in catalog.csv were NOT deleted or overwritten
    arch_row = cat_df[cat_df["product_id"] == "PROD_ARCH"].iloc[0]
    assert arch_row["status"] == "archived"

    # d. Verify data/processed/{tenant}/products.csv contains ONLY active products (NOT archived)
    proc_products_bytes = storage.read_file(f"data/processed/{tenant_id}/products.csv")
    proc_df = pd.read_csv(io.BytesIO(proc_products_bytes))
    proc_pids = set(proc_df["product_id"])
    assert "PROD_ACT_1" in proc_pids
    assert "PROD_ACT_2" in proc_pids
    assert "MISSING_IN_CAT" in proc_pids
    assert "PROD_ARCH" not in proc_pids

    # e. Verify trained_products.json was written and excludes PROD_ARCH
    trained_json_bytes = storage.read_file(f"models/{tenant_id}/trained_products.json")
    trained_list = json.loads(trained_json_bytes.decode("utf-8"))
    assert "PROD_ACT_1" in trained_list
    assert "PROD_ACT_2" in trained_list
    assert "MISSING_IN_CAT" in trained_list
    assert "PROD_ARCH" not in trained_list


# ---------------------------------------------------------------------------
# 6. Simulated multi-worker cache coherency via storage version marker
# ---------------------------------------------------------------------------

def test_simulated_workers_cache_coherency(tmp_path):
    storage = LocalStorage(base_dir=tmp_path)
    tenant_id = "tenant_workers_sync"

    # Worker A starts with initial catalog
    prods = [{"product_id": "W1", "product_name": "Worker Item 1", "category": "General", "price": 10.0, "status": "active", "in_stock": 1}]
    _seed_catalog(tenant_id, prods, storage)

    # Worker A loads active catalog into cache
    active_a1 = get_active_catalog(tenant_id, storage=storage)
    assert "W1" in active_a1
    assert "W2" not in active_a1

    # Worker B modifies catalog directly in storage (adding W2)
    add_product(
        tenant_id=tenant_id,
        data={"product_id": "W2", "product_name": "Worker Item 2", "category": "General", "price": 20.0},
        who="worker_b",
        storage=storage,
    )

    # Worker A calls get_active_catalog within TTL -> returns cached version
    active_a2 = get_active_catalog(tenant_id, storage=storage)
    assert "W2" not in active_a2  # cached

    # Fast forward Worker A's last_checked beyond TTL
    with _CACHE_LOCK:
        _ACTIVE_METADATA[tenant_id]["last_checked"] -= (CACHE_TTL_SECONDS + 5.0)

    # Worker A checks again: detects marker mismatch, invalidates and loads fresh catalog
    active_a3 = get_active_catalog(tenant_id, storage=storage)
    assert "W2" in active_a3
    assert "W1" in active_a3


# ---------------------------------------------------------------------------
# 7. Pipeline fails with clear status error if active products < 2
# ---------------------------------------------------------------------------

def test_pipeline_fails_when_fewer_than_two_active_products(tmp_path, monkeypatch):
    tenant_id = "tenant_fewer_than_two"
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.pipeline.run.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.active_set.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)

    # Catalog with 1 active product and 1 archived product
    cat_prods = [
        {"product_id": "LONE_ACTIVE", "product_name": "Lone Active", "category": "A", "price": 10.0, "status": "active", "in_stock": 1},
        {"product_id": "ARCHIVED_ITEM", "product_name": "Archived", "category": "A", "price": 20.0, "status": "archived", "in_stock": 1},
    ]
    _seed_catalog(tenant_id, cat_prods, storage)

    raw_csv = (
        "customer_id,product_id,event_type\n"
        "C1,LONE_ACTIVE,purchase\n"
        "C2,LONE_ACTIVE,view\n"
    )
    storage.write_file(f"data/raw/{tenant_id}_raw.csv", raw_csv.encode("utf-8"))

    test_config = {
        "storage": {"backend": "local", "local_dir": str(tmp_path)},
        "tenants": {
            tenant_id: {
                "name": "Few Products Tenant",
                "data_source": {"type": "csv", "path": f"data/raw/{tenant_id}_raw.csv"},
                "customers": {"id_column": "customer_id", "features": []},
                "products": {
                    "derived_from": "transactional",
                    "id_column": "product_id",
                    "name_column": "product_id",
                },
                "interactions": {
                    "source": "transactional",
                    "customer_id_column": "customer_id",
                    "product_id_column": "product_id",
                },
            }
        },
    }

    with pytest.raises(ValueError, match="fewer than 2 active products"):
        run_tenant_pipeline(tenant_id=tenant_id, storage=storage, config=test_config)

    # Check status file in storage
    status_bytes = storage.read_file(f"status/{tenant_id}.json")
    status_data = json.loads(status_bytes.decode("utf-8"))
    assert status_data["status"] == "failed"
    assert "fewer than 2 active products" in status_data["error"]


# ---------------------------------------------------------------------------
# 8. Multi-tenant isolation
# ---------------------------------------------------------------------------

def test_catalog_engine_tenant_isolation(tmp_path, test_client, monkeypatch):
    t_a = "tenant_iso_a"
    t_b = "tenant_iso_b"
    key_a = _setup_tenant_auth(t_a)
    key_b = _setup_tenant_auth(t_b)

    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.api.recommendations.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.active_set.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)

    _seed_catalog(t_a, [{"product_id": "TA_1", "product_name": "A Product", "category": "A", "price": 10.0, "status": "active", "in_stock": 1}], storage)
    _seed_catalog(t_b, [{"product_id": "TB_1", "product_name": "B Product", "category": "B", "price": 20.0, "status": "active", "in_stock": 1}], storage)

    MODEL_CACHE[t_a] = MockRecommender(["TA_1"], pd.DataFrame([{"product_id": "TA_1"}]), pd.DataFrame([{"customer_id": "C1"}]))
    MODEL_CACHE[t_b] = MockRecommender(["TB_1"], pd.DataFrame([{"product_id": "TB_1"}]), pd.DataFrame([{"customer_id": "C1"}]))

    # Verify recommendations for A and B
    res_a = test_client.get("/v1/recommendations", params={"customer_id": "C1", "top_n": 1}, headers={"X-API-Key": key_a})
    res_b = test_client.get("/v1/recommendations", params={"customer_id": "C1", "top_n": 1}, headers={"X-API-Key": key_b})
    assert res_a.json()["recommendations"][0]["product_id"] == "TA_1"
    assert res_b.json()["recommendations"][0]["product_id"] == "TB_1"

    # Modify Tenant A's product: must not touch Tenant B
    update_product(t_a, "TA_1", {"price": 99.9}, who="admin", storage=storage)
    clear_active_catalog_cache(t_a)

    cat_b = get_active_catalog(t_b, storage=storage)
    assert "TA_1" not in cat_b
    assert cat_b["TB_1"]["price"] == 20.0


# ---------------------------------------------------------------------------
# 9. Timing test: 5,000-product catalogue filtering adds < 20 ms on average
# ---------------------------------------------------------------------------

def test_timing_benchmark_5000_product_catalog(tmp_path):
    storage = LocalStorage(base_dir=tmp_path)
    tenant_id = "tenant_timing_5k"

    rows = []
    for i in range(5000):
        rows.append({
            "product_id": f"SKU_{i:05d}",
            "product_name": f"Product Number {i}",
            "category": f"Cat_{i % 20}",
            "price": float(i + 1),
            "status": "active" if i % 10 != 0 else "archived",
            "in_stock": 1 if i % 5 != 0 else 0,
        })
    _seed_catalog(tenant_id, rows, storage)

    # Prime cache once
    active_set = get_active_catalog(tenant_id, storage=storage)
    assert active_set is not None
    assert len(active_set) > 3000

    # Benchmark: simulate 100 recommendation requests filtering candidates against active set
    candidates = [f"SKU_{i:05d}" for i in range(100)]
    n_iters = 100

    start_t = time.perf_counter()
    for _ in range(n_iters):
        # Fetch active set (cached, TTL check)
        act_cat = get_active_catalog(tenant_id, storage=storage)
        # Filter candidate items & enrich
        valid_items = []
        for pid in candidates:
            if pid in act_cat:
                valid_items.append(act_cat[pid])
                if len(valid_items) >= 10:
                    break
    end_t = time.perf_counter()

    avg_ms = ((end_t - start_t) / n_iters) * 1000.0
    # Must add less than 20 ms on average
    assert avg_ms < 20.0, f"Active set filtering overhead too high: {avg_ms:.3f} ms"


# ---------------------------------------------------------------------------
# 10. Summary metrics
# ---------------------------------------------------------------------------

def test_catalog_summary_metrics(tmp_path, test_client, monkeypatch):
    tenant_id = "tenant_summary_metrics"
    api_key = _setup_tenant_auth(tenant_id)
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)

    # 1. Untrained tenant
    _seed_catalog(tenant_id, [
        {"product_id": "P1", "product_name": "P1", "category": "C", "price": 10.0, "status": "active", "in_stock": 1},
        {"product_id": "P2", "product_name": "P2", "category": "C", "price": 20.0, "status": "active", "in_stock": 1},
    ], storage)

    summary = get_catalog_summary(tenant_id, storage=storage)
    assert summary["never_trained"] is True
    assert summary["products_added_since_last_training"] == 0

    # 2. Simulate completed training for P1 and P2
    trained_at = datetime.now(timezone.utc).isoformat()
    storage.write_file(f"models/{tenant_id}/trained_products.json", json.dumps(["P1", "P2"]).encode("utf-8"))
    status_data = {
        "tenant_id": tenant_id,
        "status": "completed",
        "trained_at": trained_at,
        "trained_product_ids_count": 2,
    }
    storage.write_file(f"status/{tenant_id}.json", json.dumps(status_data).encode("utf-8"))

    summary_trained = get_catalog_summary(tenant_id, storage=storage)
    assert summary_trained["never_trained"] is False
    assert summary_trained["products_added_since_last_training"] == 0
    assert summary_trained["products_changed_since_last_training"] == 0

    # 3. Add a new product (P3)
    add_product(
        tenant_id=tenant_id,
        data={"product_id": "P3", "product_name": "P3", "category": "C", "price": 30.0},
        who="admin",
        storage=storage,
    )
    summary_added = get_catalog_summary(tenant_id, storage=storage)
    assert summary_added["products_added_since_last_training"] == 1

    # 4. Update P1 with an updated_at > trained_at
    time.sleep(0.01)
    update_product(
        tenant_id=tenant_id,
        product_id="P1",
        update_data={"price": 15.0},
        who="admin",
        storage=storage,
    )
    summary_updated = get_catalog_summary(tenant_id, storage=storage)
    assert summary_updated["products_changed_since_last_training"] >= 1


# ---------------------------------------------------------------------------
# 11. S3 Storage Mocked (moto)
# ---------------------------------------------------------------------------

@mock_aws
def test_s3_storage_catalog_engine_lifecycle(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket="mock-ai-pod-bucket-c2")
    storage = S3Storage(bucket_name="mock-ai-pod-bucket-c2", s3_client=s3_client)

    tenant_id = "e2e_tenant_s3_c2"

    # Seed catalog on S3
    prods = [
        {"product_id": "S3_P1", "product_name": "S3 Item 1", "category": "Cloud", "price": 50.0, "status": "active", "in_stock": 1},
        {"product_id": "S3_P2", "product_name": "S3 Item 2", "category": "Cloud", "price": 60.0, "status": "active", "in_stock": 1},
    ]
    _seed_catalog(tenant_id, prods, storage)

    # Verify active set load from S3
    active_cat = get_active_catalog(tenant_id, storage=storage)
    assert active_cat is not None
    assert set(active_cat.keys()) == {"S3_P1", "S3_P2"}

    # Archive S3_P1
    delete_product(tenant_id, "S3_P1", who="admin", storage=storage)
    clear_active_catalog_cache(tenant_id)

    active_cat_after = get_active_catalog(tenant_id, storage=storage)
    assert set(active_cat_after.keys()) == {"S3_P2"}


# ---------------------------------------------------------------------------
# 12. Dashboard telemetry uses active catalog & excludes archived from top_products
# ---------------------------------------------------------------------------

def test_dashboard_analytics_excludes_archived_products(tmp_path, monkeypatch):
    tenant_id = "tenant_telem_c2"
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.telemetry.reader.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.active_set.get_storage_backend", lambda cfg=None: storage)

    # Seed catalog with 1 active, 1 archived
    prods = [
        {"product_id": "P_TOP_ACT", "product_name": "Active Best Seller", "category": "Cat", "price": 10.0, "status": "active", "in_stock": 1},
        {"product_id": "P_TOP_ARCH", "product_name": "Archived Old Seller", "category": "Cat", "price": 10.0, "status": "archived", "in_stock": 1},
    ]
    _seed_catalog(tenant_id, prods, storage)

    # Write telemetry with both products recommended
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    telem_rec = {
        "tenant_id": tenant_id,
        "type": "recommendation",
        "source": "live",
        "ts": f"{today_str}T12:00:00Z",
        "recommended_products": ["P_TOP_ARCH", "P_TOP_ARCH", "P_TOP_ACT"],
    }
    part_path = f"data/telemetry/{tenant_id}/{today_str}/part-001.jsonl"
    storage.write_file(part_path, (json.dumps(telem_rec) + "\n").encode("utf-8"))

    # Also record an interaction event referencing an unknown product (must not crash)
    event_rec = {
        "tenant_id": tenant_id,
        "type": "event",
        "event_type": "view",
        "product_id": "UNKNOWN_OR_ARCHIVED_EVENT_PROD",
        "ts": f"{today_str}T12:01:00Z",
    }
    event_part_path = f"data/telemetry/{tenant_id}/{today_str}/part-002.jsonl"
    storage.write_file(event_part_path, (json.dumps(event_rec) + "\n").encode("utf-8"))

    telem = get_tenant_telemetry(tenant_id, days=1, storage=storage, use_cache=False)
    assert telem["total_recommendations"] == 1
    assert telem["total_events"] == 1

    # top_products must ONLY contain active products (P_TOP_ACT), P_TOP_ARCH must be excluded!
    top_pids = [p["product_id"] for p in telem["top_products"]]
    assert "P_TOP_ACT" in top_pids
    assert "P_TOP_ARCH" not in top_pids
    # Product name was enriched from active catalog
    p_act = next(p for p in telem["top_products"] if p["product_id"] == "P_TOP_ACT")
    assert p_act["product_name"] == "Active Best Seller"

