"""Tests for Similar Products feature (Step C3).

Verifies:
1. Two phones with similar specs rank above a laptop.
2. A tablet from another category is excluded when same_category=true and may appear when false.
3. Price band filter (max_price_ratio).
4. Archived product disappears within cache TTL and returns after restore.
5. Brand-new product appears in similar results for a related product without retraining.
6. Out-of-stock products hidden when catalog.hide_out_of_stock is true.
7. Product with no specs still gets category/brand/text based results with sensible reasons.
8. Unknown product returns HTTP 200 with fallback=true and reason='unknown_product'.
9. Inactive/archived product returns HTTP 200 with fallback=true and reason='inactive_product'.
10. Tenant without a catalogue works from data/processed/{tenant}/products.csv read-only.
11. Tenant isolation (candidates from tenant A never leak to tenant B).
12. Authentication: pk- allowed, missing key returns 401, pk- blocked on admin routes.
13. Telemetry & Dashboard: similar requests do NOT change dashboard recommendation counts or fallback rate.
14. Mocked S3 storage flow (moto).
15. Multi-worker cache coherency: simulated second worker sees catalogue changes within TTL.
16. Performance benchmark: average request < 30ms (5,000 products) and < 150ms (50,000 products).
"""

from __future__ import annotations

import io
import time
from typing import Any

from fastapi.testclient import TestClient
from moto import mock_aws
import pandas as pd
import pytest

from src.api.app import app
from src.catalog.active_set import clear_active_catalog_cache
from src.similarity.service import clear_similarity_cache, find_similar_products
from src.storage import get_storage_backend
from src.storage.local_storage import LocalStorage
from src.telemetry.collector import clear_telemetry_buffer, flush_telemetry
from src.telemetry.reader import clear_telemetry_cache, get_tenant_telemetry


@pytest.fixture(autouse=True)
def cleanup_caches():
    clear_similarity_cache()
    clear_active_catalog_cache()
    clear_telemetry_cache()
    clear_telemetry_buffer()
    yield
    clear_similarity_cache()
    clear_active_catalog_cache()
    clear_telemetry_cache()
    clear_telemetry_buffer()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _seed_sample_catalog(storage, tenant_id: str, products: list[dict[str, Any]]) -> None:
    """Helper to write catalog.csv directly to storage."""
    df = pd.DataFrame(products)
    cat_path = f"data/catalog/{tenant_id}/catalog.csv"
    storage.write_file(cat_path, df.to_csv(index=False).encode("utf-8"))
    clear_similarity_cache(tenant_id)
    clear_active_catalog_cache(tenant_id)


# ---------------------------------------------------------------------------
# Test 1: Two phones with similar specs rank above a laptop
# ---------------------------------------------------------------------------
def test_two_phones_rank_above_laptop(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "test_specs_tenant"
    products = [
        {
            "product_id": "phone_target",
            "product_name": "Galaxy S24",
            "category": "Smartphones",
            "brand": "Samsung",
            "price": 800.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=8; storage_gb=256; screen_in=6.2",
            "description": "Premium Android smartphone with AMOLED display",
        },
        {
            "product_id": "phone_similar",
            "product_name": "Pixel 8",
            "category": "Smartphones",
            "brand": "Google",
            "price": 700.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=8; storage_gb=256; screen_in=6.2",
            "description": "Android smartphone with Google Tensor chip and crisp display",
        },
        {
            "product_id": "phone_budget",
            "product_name": "Galaxy A15",
            "category": "Smartphones",
            "brand": "Samsung",
            "price": 200.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=4; storage_gb=64; screen_in=6.5",
            "description": "Budget Android smartphone with long battery",
        },
        {
            "product_id": "laptop_flagship",
            "product_name": "Galaxy Book 4 Pro",
            "category": "Laptops",
            "brand": "Samsung",
            "price": 1400.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=32; storage_gb=1024; screen_in=16.0",
            "description": "Ultra-thin high-performance laptop with Intel Core Ultra",
        },
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    # When same_category is False, laptop can be considered, but phones with similar specs rank above it
    res = find_similar_products(
        tenant_id=tenant_id,
        product_id="phone_target",
        top_n=3,
        same_category=False,
        max_price_ratio=0.0,  # disable price ratio to allow laptop
        storage=storage,
    )
    assert res["fallback"] is False
    pids = [item["product_id"] for item in res["similar"]]

    # Both phones must rank above the laptop
    assert "phone_similar" in pids
    assert "phone_budget" in pids
    assert pids.index("phone_similar") < pids.index("phone_budget")
    if "laptop_flagship" in pids:
        assert pids.index("phone_similar") < pids.index("laptop_flagship")
        assert pids.index("phone_budget") < pids.index("laptop_flagship")

    # Check reason strings
    sim_item = res["similar"][0]
    assert any("RAM and storage" in r or "RAM" in r or "Same category" in r for r in sim_item["reasons"])


# ---------------------------------------------------------------------------
# Test 2: Category filtering (same_category=true vs false)
# ---------------------------------------------------------------------------
def test_tablet_excluded_when_same_category_true_and_appears_when_false(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "test_cat_filter"
    products = [
        {
            "product_id": "phone_1",
            "product_name": "Phone One",
            "category": "Smartphones",
            "brand": "Acme",
            "price": 500.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=6; storage_gb=128",
            "description": "Modern mobile device",
        },
        {
            "product_id": "phone_2",
            "product_name": "Phone Two",
            "category": "Smartphones",
            "brand": "Acme",
            "price": 520.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=6; storage_gb=128",
            "description": "Modern mobile device companion",
        },
        {
            "product_id": "tablet_1",
            "product_name": "Tablet Tab",
            "category": "Tablets",
            "brand": "Acme",
            "price": 510.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=6; storage_gb=128",
            "description": "Modern mobile tablet companion",
        },
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    # 1. same_category=True: tablet MUST NOT appear
    res_true = find_similar_products(
        tenant_id=tenant_id,
        product_id="phone_1",
        top_n=5,
        same_category=True,
        storage=storage,
    )
    pids_true = [item["product_id"] for item in res_true["similar"]]
    assert "phone_2" in pids_true
    assert "tablet_1" not in pids_true

    # 2. same_category=False: tablet MAY appear
    res_false = find_similar_products(
        tenant_id=tenant_id,
        product_id="phone_1",
        top_n=5,
        same_category=False,
        storage=storage,
    )
    pids_false = [item["product_id"] for item in res_false["similar"]]
    assert "tablet_1" in pids_false


# ---------------------------------------------------------------------------
# Test 3: Price band filter (max_price_ratio)
# ---------------------------------------------------------------------------
def test_price_band_filter(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "test_price_ratio"
    products = [
        {
            "product_id": "p_base",
            "product_name": "Base TV",
            "category": "Televisions",
            "brand": "Sony",
            "price": 1000.0,
            "in_stock": 1,
            "status": "active",
            "specs": "screen_in=55",
            "description": "4K Smart TV",
        },
        {
            "product_id": "p_allowed_high",
            "product_name": "High TV",
            "category": "Televisions",
            "brand": "Sony",
            "price": 1800.0,  # 1.8x <= 2.0x
            "in_stock": 1,
            "status": "active",
            "specs": "screen_in=55",
            "description": "4K OLED Smart TV",
        },
        {
            "product_id": "p_allowed_low",
            "product_name": "Low TV",
            "category": "Televisions",
            "brand": "Sony",
            "price": 600.0,  # 0.6x >= 0.5x
            "in_stock": 1,
            "status": "active",
            "specs": "screen_in=50",
            "description": "4K LED Smart TV",
        },
        {
            "product_id": "p_rejected_expensive",
            "product_name": "Luxury TV",
            "category": "Televisions",
            "brand": "Sony",
            "price": 3000.0,  # 3.0x > 2.0x -> REJECTED
            "in_stock": 1,
            "status": "active",
            "specs": "screen_in=85",
            "description": "8K Master Series TV",
        },
        {
            "product_id": "p_rejected_cheap",
            "product_name": "Mini TV",
            "category": "Televisions",
            "brand": "Sony",
            "price": 200.0,  # 0.2x < 0.5x -> REJECTED
            "in_stock": 1,
            "status": "active",
            "specs": "screen_in=24",
            "description": "Compact HD TV",
        },
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    res = find_similar_products(
        tenant_id=tenant_id,
        product_id="p_base",
        top_n=5,
        same_category=True,
        max_price_ratio=2.0,
        storage=storage,
    )
    pids = [item["product_id"] for item in res["similar"]]
    assert "p_allowed_high" in pids
    assert "p_allowed_low" in pids
    assert "p_rejected_expensive" not in pids
    assert "p_rejected_cheap" not in pids


# ---------------------------------------------------------------------------
# Test 4: Archived product disappears within cache TTL and returns after restore
# ---------------------------------------------------------------------------
def test_archived_product_disappears_and_returns_after_restore(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "test_archive_restore"
    products = [
        {"product_id": "item_1", "product_name": "Widget A", "category": "Widgets", "brand": "BrandX", "price": 10.0, "in_stock": 1, "status": "active"},
        {"product_id": "item_2", "product_name": "Widget B", "category": "Widgets", "brand": "BrandX", "price": 11.0, "in_stock": 1, "status": "active"},
        {"product_id": "item_3", "product_name": "Widget C", "category": "Widgets", "brand": "BrandX", "price": 12.0, "in_stock": 1, "status": "active"},
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    # Initially item_2 appears in similar items of item_1
    res1 = find_similar_products(tenant_id=tenant_id, product_id="item_1", top_n=2, storage=storage)
    pids1 = [item["product_id"] for item in res1["similar"]]
    assert "item_2" in pids1

    # Archive item_2
    products[1]["status"] = "archived"
    _seed_sample_catalog(storage, tenant_id, products)

    # item_2 disappears
    res2 = find_similar_products(tenant_id=tenant_id, product_id="item_1", top_n=2, storage=storage)
    pids2 = [item["product_id"] for item in res2["similar"]]
    assert "item_2" not in pids2

    # Querying archived item_2 directly gives HTTP 200 with fallback=True, reason="inactive_product"
    res_archived = find_similar_products(tenant_id=tenant_id, product_id="item_2", top_n=2, storage=storage)
    assert res_archived["fallback"] is True
    assert res_archived["reason"] == "inactive_product"

    # Restore item_2
    products[1]["status"] = "active"
    _seed_sample_catalog(storage, tenant_id, products)

    res3 = find_similar_products(tenant_id=tenant_id, product_id="item_1", top_n=2, storage=storage)
    pids3 = [item["product_id"] for item in res3["similar"]]
    assert "item_2" in pids3


# ---------------------------------------------------------------------------
# Test 5: Brand-new product appears in similar results without retraining
# ---------------------------------------------------------------------------
def test_new_product_appears_without_retraining(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "test_new_product"
    products = [
        {"product_id": "shoe_1", "product_name": "Running Shoe Classic", "category": "Footwear", "brand": "Nike", "price": 120.0, "in_stock": 1, "status": "active"},
        {"product_id": "shoe_2", "product_name": "Trail Shoe Explorer", "category": "Footwear", "brand": "Salomon", "price": 130.0, "in_stock": 1, "status": "active"},
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    res1 = find_similar_products(tenant_id=tenant_id, product_id="shoe_1", top_n=5, storage=storage)
    pids1 = [item["product_id"] for item in res1["similar"]]
    assert "shoe_new" not in pids1

    # Add brand-new product directly to catalogue
    products.append({
        "product_id": "shoe_new",
        "product_name": "Running Shoe Pro Next",
        "category": "Footwear",
        "brand": "Nike",
        "price": 125.0,
        "in_stock": 1,
        "status": "active",
        "description": "Next generation lightweight road running shoe",
    })
    _seed_sample_catalog(storage, tenant_id, products)

    # Immediately visible without retraining
    res2 = find_similar_products(tenant_id=tenant_id, product_id="shoe_1", top_n=5, storage=storage)
    pids2 = [item["product_id"] for item in res2["similar"]]
    assert "shoe_new" in pids2
    # shoe_new matches brand and name/category, should be top result
    assert pids2[0] == "shoe_new"


# ---------------------------------------------------------------------------
# Test 6: Out-of-stock products hidden when catalog.hide_out_of_stock is true
# ---------------------------------------------------------------------------
def test_out_of_stock_hidden(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "test_stock_hidden"
    products = [
        {"product_id": "cup_1", "product_name": "Ceramic Mug", "category": "Kitchen", "brand": "Home", "price": 15.0, "in_stock": 1, "status": "active"},
        {"product_id": "cup_2", "product_name": "Travel Mug", "category": "Kitchen", "brand": "Home", "price": 18.0, "in_stock": 0, "status": "active"},  # Out of stock
        {"product_id": "cup_3", "product_name": "Glass Cup", "category": "Kitchen", "brand": "Home", "price": 12.0, "in_stock": 1, "status": "active"},
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    res = find_similar_products(tenant_id=tenant_id, product_id="cup_1", top_n=3, storage=storage)
    pids = [item["product_id"] for item in res["similar"]]
    assert "cup_3" in pids
    assert "cup_2" not in pids


# ---------------------------------------------------------------------------
# Test 7: Product with no specs gets category/brand/text based results with reasons
# ---------------------------------------------------------------------------
def test_product_with_no_specs_gets_sensible_reasons(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "test_no_specs"
    products = [
        {
            "product_id": "shirt_1",
            "product_name": "Cotton Polo Shirt Navy",
            "category": "Apparel",
            "brand": "Ralph",
            "price": 95.0,
            "in_stock": 1,
            "status": "active",
            "description": "Breathable 100% cotton polo shirt with embroidered logo",
        },
        {
            "product_id": "shirt_2",
            "product_name": "Cotton Polo Shirt Black",
            "category": "Apparel",
            "brand": "Ralph",
            "price": 95.0,
            "in_stock": 1,
            "status": "active",
            "description": "Classic breathable cotton polo shirt",
        },
        {
            "product_id": "jeans_1",
            "product_name": "Denim Jeans",
            "category": "Apparel",
            "brand": "Levi",
            "price": 70.0,
            "in_stock": 1,
            "status": "active",
            "description": "Classic straight fit denim jeans",
        },
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    res = find_similar_products(tenant_id=tenant_id, product_id="shirt_1", top_n=2, storage=storage)
    assert res["fallback"] is False
    assert len(res["similar"]) >= 1

    top_item = res["similar"][0]
    assert top_item["product_id"] == "shirt_2"
    assert "Same category" in top_item["reasons"]
    assert "Same brand" in top_item["reasons"]
    assert "Same price" in top_item["reasons"] or "Similar price" in top_item["reasons"]


# ---------------------------------------------------------------------------
# Test 8: Unknown product returns 200 with fallback=true, reason='unknown_product'
# ---------------------------------------------------------------------------
def test_unknown_product_returns_200_fallback(tmp_path, monkeypatch, client: TestClient):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "telco_default"
    # Even if products exist, an unknown product ID returns 200 with fallback
    products = [
        {"product_id": "prod_100", "product_name": "Item 100", "category": "General", "brand": "Acme", "price": 10.0, "in_stock": 1, "status": "active"}
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    resp = client.get(
        "/v1/recommendations/similar/totally_unknown_product_id",
        headers={"X-API-Key": "sk-telco_default-xxxx"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fallback"] is True
    assert data["reason"] == "unknown_product"
    assert data["product_id"] == "totally_unknown_product_id"


# ---------------------------------------------------------------------------
# Test 9: Tenant without catalogue works from processed products.csv read-only
# ---------------------------------------------------------------------------
def test_tenant_without_catalogue_works_from_processed(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "processed_only_tenant"
    # Write only data/processed/{tenant}/products.csv (no data/catalog/)
    proc_df = pd.DataFrame([
        {"product_id": "pr_1", "product_name": "Processed Headset", "category": "Audio", "brand": "Sony", "price": 150.0},
        {"product_id": "pr_2", "product_name": "Processed Earbuds", "category": "Audio", "brand": "Sony", "price": 130.0},
    ])
    proc_path = f"data/processed/{tenant_id}/products.csv"
    storage.write_file(proc_path, proc_df.to_csv(index=False).encode("utf-8"))

    res = find_similar_products(tenant_id=tenant_id, product_id="pr_1", top_n=2, storage=storage)
    assert res["fallback"] is False
    pids = [item["product_id"] for item in res["similar"]]
    assert "pr_2" in pids
    assert res["similar"][0]["product_name"] == "Processed Earbuds"


# ---------------------------------------------------------------------------
# Test 10: Tenant isolation
# ---------------------------------------------------------------------------
def test_tenant_isolation(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_a = "tenant_alpha"
    tenant_b = "tenant_beta"

    _seed_sample_catalog(storage, tenant_a, [
        {"product_id": "secret_a_1", "product_name": "Alpha Secret 1", "category": "Confidential", "brand": "Alpha", "price": 100.0, "in_stock": 1, "status": "active"},
        {"product_id": "secret_a_2", "product_name": "Alpha Secret 2", "category": "Confidential", "brand": "Alpha", "price": 105.0, "in_stock": 1, "status": "active"},
    ])

    _seed_sample_catalog(storage, tenant_b, [
        {"product_id": "item_b_1", "product_name": "Beta Item 1", "category": "Public", "brand": "Beta", "price": 50.0, "in_stock": 1, "status": "active"},
        {"product_id": "item_b_2", "product_name": "Beta Item 2", "category": "Public", "brand": "Beta", "price": 55.0, "in_stock": 1, "status": "active"},
    ])

    # Tenant B queries item_b_1; must NEVER see secret_a_*
    res_b = find_similar_products(tenant_id=tenant_b, product_id="item_b_1", top_n=5, storage=storage)
    b_pids = [item["product_id"] for item in res_b["similar"]]
    assert "item_b_2" in b_pids
    assert "secret_a_1" not in b_pids
    assert "secret_a_2" not in b_pids


# ---------------------------------------------------------------------------
# Test 11: Auth: pk- allowed, missing key 401, pk- blocked on admin routes
# ---------------------------------------------------------------------------
def test_auth_pk_allowed_and_admin_blocked(tmp_path, monkeypatch, client: TestClient):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "telco_default"
    _seed_sample_catalog(storage, tenant_id, [
        {"product_id": "phone_1", "product_name": "Phone One", "category": "Tech", "brand": "Brand", "price": 100.0, "in_stock": 1, "status": "active"},
        {"product_id": "phone_2", "product_name": "Phone Two", "category": "Tech", "brand": "Brand", "price": 110.0, "in_stock": 1, "status": "active"},
    ])

    # 1. No key -> 401
    r_no_key = client.get("/v1/recommendations/similar/phone_1")
    assert r_no_key.status_code == 401

    # 2. Public key (pk-) -> 200 allowed
    r_pk = client.get(
        "/v1/recommendations/similar/phone_1",
        headers={"X-API-Key": "pk-telco_default-xxxx"},
    )
    assert r_pk.status_code == 200
    assert r_pk.json()["product_id"] == "phone_1"

    # 3. Public key on admin route (e.g. /v1/catalog/summary) -> 403 Forbidden
    r_admin_pk = client.get(
        "/v1/catalog/summary",
        headers={"X-API-Key": "pk-telco_default-xxxx"},
    )
    assert r_admin_pk.status_code == 403

    # 4. Private key (sk-) on similar route -> 200 allowed
    r_sk = client.get(
        "/v1/recommendations/similar/phone_1",
        headers={"X-API-Key": "sk-telco_default-xxxx"},
    )
    assert r_sk.status_code == 200


# ---------------------------------------------------------------------------
# Test 12: Telemetry: similar requests do NOT change recommendation counts
# ---------------------------------------------------------------------------
def test_similar_requests_do_not_change_recommendation_counts(tmp_path, monkeypatch, client: TestClient):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "telco_default"
    _seed_sample_catalog(storage, tenant_id, [
        {"product_id": "sim_p1", "product_name": "Product 1", "category": "Tech", "brand": "Brand", "price": 10.0, "in_stock": 1, "status": "active"},
        {"product_id": "sim_p2", "product_name": "Product 2", "category": "Tech", "brand": "Brand", "price": 12.0, "in_stock": 1, "status": "active"},
    ])

    # Get initial dashboard analytics
    telem_initial = get_tenant_telemetry(tenant_id, storage=storage, use_cache=False)
    initial_recs = telem_initial.get("total_recommendations", 0)
    initial_similar = telem_initial.get("similar_requests", 0)

    # Perform 3 similar product requests
    for _ in range(3):
        resp = client.get(
            "/v1/recommendations/similar/sim_p1",
            headers={"X-API-Key": "sk-telco_default-xxxx"},
        )
        assert resp.status_code == 200

    flush_telemetry(storage)
    clear_telemetry_cache()

    telem_after = get_tenant_telemetry(tenant_id, storage=storage, use_cache=False)
    # total_recommendations must be UNCHANGED
    assert telem_after.get("total_recommendations", 0) == initial_recs
    # similar_requests must have increased by 3
    assert telem_after.get("similar_requests", 0) == initial_similar + 3
    # Top similar source products must list sim_p1
    src_products = [p["product_id"] for p in telem_after.get("top_similar_source_products", [])]
    assert "sim_p1" in src_products


# ---------------------------------------------------------------------------
# Test 13: Mocked S3 storage flow
# ---------------------------------------------------------------------------
@mock_aws
def test_s3_storage_similar_lifecycle(monkeypatch):
    import boto3
    from src.storage.s3_storage import S3Storage

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-similar-bucket")

    s3_storage = S3Storage(bucket_name="test-similar-bucket", prefix="ai_pod", region_name="us-east-1", s3_client=s3)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: s3_storage)

    tenant_id = "s3_similar_tenant"
    products = [
        {"product_id": "s3_item_1", "product_name": "Cloud Camera", "category": "Electronics", "brand": "Sony", "price": 900.0, "in_stock": 1, "status": "active"},
        {"product_id": "s3_item_2", "product_name": "Cloud Lens", "category": "Electronics", "brand": "Sony", "price": 850.0, "in_stock": 1, "status": "active"},
    ]
    _seed_sample_catalog(s3_storage, tenant_id, products)

    res = find_similar_products(tenant_id=tenant_id, product_id="s3_item_1", top_n=2, storage=s3_storage)
    assert res["fallback"] is False
    assert res["similar"][0]["product_id"] == "s3_item_2"


# ---------------------------------------------------------------------------
# Test 14: Simulated second worker cache coherency
# ---------------------------------------------------------------------------
def test_simulated_second_worker_cache_coherency(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    tenant_id = "worker_sync_tenant"
    products = [
        {"product_id": "item_alpha", "product_name": "Alpha Item", "category": "General", "brand": "Brand", "price": 10.0, "in_stock": 1, "status": "active"},
        {"product_id": "item_beta", "product_name": "Beta Item", "category": "General", "brand": "Brand", "price": 12.0, "in_stock": 1, "status": "active"},
    ]
    _seed_sample_catalog(storage, tenant_id, products)

    # Worker 1 warms its cache
    res1 = find_similar_products(tenant_id=tenant_id, product_id="item_alpha", top_n=2, storage=storage)
    assert res1["similar"][0]["product_id"] == "item_beta"

    # Worker 2 mutates catalogue file directly on storage (simulating external process)
    products.append({
        "product_id": "item_gamma",
        "product_name": "Gamma Ultra Match",
        "category": "General",
        "brand": "Brand",
        "price": 10.5,
        "in_stock": 1,
        "status": "active",
        "description": "Exact match for alpha item",
    })
    cat_path = f"data/catalog/{tenant_id}/catalog.csv"
    storage.write_file(cat_path, pd.DataFrame(products).to_csv(index=False).encode("utf-8"))

    # Fast forward TTL in both similarity and active_set metadata to simulate 20s passing on the worker
    from src.similarity.service import _SIMILARITY_LOCK, _SIMILARITY_METADATA
    from src.catalog.active_set import _CACHE_LOCK as _ACT_LOCK, _ACTIVE_METADATA
    with _SIMILARITY_LOCK:
        if tenant_id in _SIMILARITY_METADATA:
            _SIMILARITY_METADATA[tenant_id]["last_checked"] -= 20.0
    with _ACT_LOCK:
        if tenant_id in _ACTIVE_METADATA:
            _ACTIVE_METADATA[tenant_id]["last_checked"] -= 20.0

    # Worker 1 runs again: detects marker change and picks up item_gamma without restart
    res2 = find_similar_products(tenant_id=tenant_id, product_id="item_alpha", top_n=2, storage=storage)
    pids = [item["product_id"] for item in res2["similar"]]
    assert "item_gamma" in pids


# ---------------------------------------------------------------------------
# Test 15: Performance benchmark (5,000 and 50,000 products)
# ---------------------------------------------------------------------------
def test_performance_benchmark_5k_and_50k(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.storage.get_storage_backend", lambda *args, **kwargs: storage)

    # 1. Benchmark 5,000 products (< 30 ms)
    tenant_5k = "perf_5k_tenant"
    products_5k = []
    categories = ["Smartphones", "Laptops", "Audio", "Tablets", "Wearables"]
    brands = ["Apple", "Samsung", "Sony", "Dell", "Bose"]

    for i in range(5000):
        cat = categories[i % len(categories)]
        brand = brands[i % len(brands)]
        price = 50.0 + (i % 1000)
        ram = 4 * ((i % 8) + 1)
        storage_gb = 64 * ((i % 8) + 1)
        products_5k.append({
            "product_id": f"p_5k_{i}",
            "product_name": f"{brand} {cat} Model {i}",
            "category": cat,
            "brand": brand,
            "price": price,
            "in_stock": 1,
            "status": "active",
            "specs": f"ram_gb={ram}; storage_gb={storage_gb}",
            "description": f"High quality {cat} by {brand} with reliable performance",
        })

    _seed_sample_catalog(storage, tenant_5k, products_5k)

    # Warm up cache
    find_similar_products(tenant_id=tenant_5k, product_id="p_5k_0", top_n=4, storage=storage)

    # Measure 20 warmed requests
    latencies_5k = []
    for q_idx in range(10, 30):
        t0 = time.perf_counter()
        res = find_similar_products(
            tenant_id=tenant_5k,
            product_id=f"p_5k_{q_idx}",
            top_n=4,
            same_category=True,
            storage=storage,
        )
        latencies_5k.append((time.perf_counter() - t0) * 1000.0)
        assert res["fallback"] is False

    avg_5k = sum(latencies_5k) / len(latencies_5k)
    print(f"\n[BENCHMARK] 5,000 items average warmed latency: {avg_5k:.2f} ms")
    assert avg_5k < 30.0, f"5,000 item latency exceeded 30ms limit: {avg_5k:.2f} ms"

    # 2. Benchmark 50,000 products (< 150 ms)
    tenant_50k = "perf_50k_tenant"
    products_50k = []
    for i in range(50000):
        cat = categories[i % len(categories)]
        brand = brands[i % len(brands)]
        price = 30.0 + (i % 2000)
        ram = 4 * ((i % 8) + 1)
        storage_gb = 64 * ((i % 8) + 1)
        products_50k.append({
            "product_id": f"p_50k_{i}",
            "product_name": f"{brand} {cat} Pro {i}",
            "category": cat,
            "brand": brand,
            "price": price,
            "in_stock": 1,
            "status": "active",
            "specs": f"ram_gb={ram}; storage_gb={storage_gb}",
            "description": f"Enterprise edition {cat} designed by {brand} for high productivity",
        })

    _seed_sample_catalog(storage, tenant_50k, products_50k)

    # Warm up cache
    find_similar_products(tenant_id=tenant_50k, product_id="p_50k_0", top_n=4, storage=storage)

    # Measure 20 warmed requests
    latencies_50k = []
    for q_idx in range(10, 30):
        t0 = time.perf_counter()
        res = find_similar_products(
            tenant_id=tenant_50k,
            product_id=f"p_50k_{q_idx}",
            top_n=4,
            same_category=True,
            storage=storage,
        )
        latencies_50k.append((time.perf_counter() - t0) * 1000.0)
        assert res["fallback"] is False

    avg_50k = sum(latencies_50k) / len(latencies_50k)
    print(f"\n[BENCHMARK] 50,000 items average warmed latency: {avg_50k:.2f} ms")
    assert avg_50k < 150.0, f"50,000 item latency exceeded 150ms limit: {avg_50k:.2f} ms"
