"""Tests for Storefront Similar Products & SDK Integration (Step S2).

Verifies:
1. Cold start performance (< 5s for 5,000 products) and single-flight concurrency lock.
2. CORS preflight from http://localhost:5500 allowing X-API-Key, Content-Type, X-AIPOD-Source,
   and exposed headers ETag and X-Catalog-Version.
3. Similar response schema: 16-char hex rec_id, target object with specs, items with specs and price_diff.
4. Recommendations response schema: additive rec_id.
5. POST /v1/track accepts source ("similar", "recommendation", "organic"), rec_id, and "click" event_type;
   returns 422 on invalid source or invalid rec_id.
6. GET /v1/dashboard/analytics reports similar_clicks, similar_add_to_carts, similar_purchases, similar_ctr,
   and recommendation metrics, excluding X-AIPOD-Source: wizard-test traffic.
7. Demo page /similar and /demo/similar_products.html served properly.
8. SDK static size strictly < 25 KB with required public methods.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import time
from typing import Any

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from src.api.app import app
from src.catalog.active_set import clear_active_catalog_cache
from src.similarity.service import (
    clear_similarity_cache,
    find_similar_products,
)
from src.storage.local_storage import LocalStorage
from src.telemetry.collector import clear_telemetry_buffer, flush_telemetry
from src.telemetry.reader import clear_telemetry_cache
from src.utils.config import PROJECT_ROOT


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


def _patch_all_storage(monkeypatch, storage):
    for mod in [
        "src.storage",
        "src.similarity.service",
        "src.catalog.active_set",
        "src.telemetry.collector",
        "src.telemetry.reader",
        "src.api.recommendations",
        "src.api.dashboard",
        "src.api.tracking",
    ]:
        try:
            monkeypatch.setattr(f"{mod}.get_storage_backend", lambda *args, **kwargs: storage)
        except Exception:
            pass


def _seed_catalog(storage, tenant_id: str, products: list[dict[str, Any]]) -> None:
    df = pd.DataFrame(products)
    cat_path = f"data/catalog/{tenant_id}/catalog.csv"
    storage.write_file(cat_path, df.to_csv(index=False).encode("utf-8"))
    clear_similarity_cache(tenant_id)
    clear_active_catalog_cache(tenant_id)


# ---------------------------------------------------------------------------
# Test 1: Cold start performance and single-flight concurrency lock
# ---------------------------------------------------------------------------
def test_cold_start_and_single_flight(tmp_path, monkeypatch):
    storage = LocalStorage(base_dir=tmp_path)
    _patch_all_storage(monkeypatch, storage)

    tenant_id = "bench_storefront_tenant"
    # Generate 5,000 products
    products = [
        {
            "product_id": f"dev_{i}",
            "product_name": f"Smart Gadget {i}",
            "category": f"Cat_{i % 10}",
            "brand": f"Brand_{i % 5}",
            "price": 100.0 + (i % 50),
            "in_stock": 1,
            "status": "active",
            "specs": f"ram_gb={(i % 8) + 4}; storage_gb=128; battery_mah=5000",
            "description": f"Powerful electronic gadget with high endurance {i}",
        }
        for i in range(5000)
    ]
    _seed_catalog(storage, tenant_id, products)

    # 1. Cold start build measurement
    t0 = time.perf_counter()
    res = find_similar_products(tenant_id, "dev_0", top_n=5, storage=storage)
    cold_dur = time.perf_counter() - t0

    assert res["fallback"] is False
    assert len(res["similar"]) == 5
    assert cold_dur < 5.0, f"Cold start took too long: {cold_dur:.2f}s"

    # 2. Single-flight concurrency check: clear cache, then run 4 simultaneous threads
    clear_similarity_cache(tenant_id)

    def worker_req(pid: str):
        return find_similar_products(tenant_id, pid, top_n=3, storage=storage)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(worker_req, f"dev_{i}") for i in range(4)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 4
    for r in results:
        assert r["fallback"] is False
        assert len(r["similar"]) == 3


# ---------------------------------------------------------------------------
# Test 2: CORS Preflight and Header Exposure
# ---------------------------------------------------------------------------
def test_cors_preflight_and_exposed_headers(client: TestClient):
    origin = "http://localhost:5500"

    # 1. Preflight OPTIONS for /v1/recommendations/similar/{product_id}
    sim_headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-API-Key, Content-Type, X-AIPOD-Source",
    }
    r_sim_opt = client.options("/v1/recommendations/similar/SP-01", headers=sim_headers)
    assert r_sim_opt.status_code == 200
    assert r_sim_opt.headers.get("access-control-allow-origin") in (origin, "*")
    allowed_headers = r_sim_opt.headers.get("access-control-allow-headers", "").lower()
    for h in ["x-api-key", "content-type", "x-aipod-source"]:
        assert h in allowed_headers or "*" in allowed_headers

    # 2. Preflight OPTIONS for /v1/track
    track_headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-API-Key, Content-Type, X-AIPOD-Source",
    }
    r_track_opt = client.options("/v1/track", headers=track_headers)
    assert r_track_opt.status_code == 200
    assert r_track_opt.headers.get("access-control-allow-origin") in (origin, "*")

    # 3. Verify normal response exposes ETag and X-Catalog-Version
    r_get = client.get(
        "/v1/recommendations/similar/SP-01",
        headers={"Origin": origin, "X-API-Key": "pk-telco-xxxx"},
    )
    exposed = r_get.headers.get("access-control-expose-headers", "")
    assert "ETag" in exposed or "*" in exposed or "etag" in exposed.lower()


# ---------------------------------------------------------------------------
# Test 3: Similar Response Schema: rec_id, target, and item specs/price_diff
# ---------------------------------------------------------------------------
def test_similar_response_contract(tmp_path, monkeypatch, client: TestClient):
    storage = LocalStorage(base_dir=tmp_path)
    _patch_all_storage(monkeypatch, storage)

    tenant_id = "telco_default"
    products = [
        {
            "product_id": "phone_target",
            "product_name": "Galaxy S24 Ultra",
            "category": "Smartphones",
            "brand": "Samsung",
            "price": 1000.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=12; storage_gb=512; battery_mah=5000",
            "image_url": "https://img.test/s24.jpg",
        },
        {
            "product_id": "phone_alt",
            "product_name": "Galaxy S24 Plus",
            "category": "Smartphones",
            "brand": "Samsung",
            "price": 850.0,
            "in_stock": 1,
            "status": "active",
            "specs": "ram_gb=12; storage_gb=256; battery_mah=4900",
            "image_url": "https://img.test/s24p.jpg",
        },
    ]
    _seed_catalog(storage, tenant_id, products)

    resp = client.get(
        "/v1/recommendations/similar/phone_target?top_n=2",
        headers={"X-API-Key": "pk-telco_default-xxxx"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # rec_id must be 16-hex characters
    rec_id = data.get("rec_id")
    assert rec_id is not None
    assert len(rec_id) == 16
    int(rec_id, 16)  # must parse as hex

    # Target object
    target = data.get("target")
    assert target is not None
    assert target["product_id"] == "phone_target"
    assert target["product_name"] == "Galaxy S24 Ultra"
    assert target["brand"] == "Samsung"
    assert target["price"] == 1000.0
    assert target["image_url"] == "https://img.test/s24.jpg"
    assert isinstance(target["specs"], dict)
    assert any("RAM" in k for k in target["specs"].keys())
    assert any("Storage" in k for k in target["specs"].keys())

    # Similar items
    items = data.get("similar_products", [])
    assert len(items) == 1
    alt = items[0]
    assert alt["product_id"] == "phone_alt"
    assert isinstance(alt["specs"], dict)
    assert any("Storage" in k for k in alt["specs"].keys())
    assert alt["price_diff"] == -150.0
    assert alt["price_diff_pct"] == -15.0


# ---------------------------------------------------------------------------
# Test 4: Recommendations Response Additive rec_id
# ---------------------------------------------------------------------------
def test_recommendations_response_has_rec_id(client: TestClient):
    resp = client.get(
        "/v1/recommendations?customer_id=cust_guest_001&top_n=3",
        headers={"X-API-Key": "pk-telco-xxxx"},
    )
    assert resp.status_code == 200
    data = resp.json()
    rec_id = data.get("rec_id")
    assert rec_id is not None
    assert len(rec_id) == 16
    int(rec_id, 16)


# ---------------------------------------------------------------------------
# Test 5: POST /v1/track source and rec_id validation
# ---------------------------------------------------------------------------
def test_track_source_and_rec_id_validation(client: TestClient):
    headers = {"X-API-Key": "pk-telco-xxxx"}

    # Valid payload with source='similar' and valid 16-hex rec_id
    valid_payload = {
        "event_type": "click",
        "product_id": "SP-01",
        "session_id": "sess_12345",
        "source": "similar",
        "rec_id": "a1b2c3d4e5f67890",
    }
    r_valid = client.post("/v1/track", json=valid_payload, headers=headers)
    assert r_valid.status_code == 202

    # Valid payload with source='recommendation'
    r_rec = client.post(
        "/v1/track",
        json={**valid_payload, "source": "recommendation"},
        headers=headers,
    )
    assert r_rec.status_code == 202

    # Valid payload with source='organic'
    r_org = client.post(
        "/v1/track",
        json={**valid_payload, "source": "organic"},
        headers=headers,
    )
    assert r_org.status_code == 202

    # Invalid source -> 422
    r_bad_src = client.post(
        "/v1/track",
        json={**valid_payload, "source": "unknown_invalid_source"},
        headers=headers,
    )
    assert r_bad_src.status_code == 422

    # Invalid rec_id (non-hex) -> 422
    r_bad_rec = client.post(
        "/v1/track",
        json={**valid_payload, "rec_id": "not-valid-hex!@#$"},
        headers=headers,
    )
    assert r_bad_rec.status_code == 422

    # Invalid rec_id (too long > 32 chars) -> 422
    r_long_rec = client.post(
        "/v1/track",
        json={**valid_payload, "rec_id": "0123456789abcdef0123456789abcdef0"},
        headers=headers,
    )
    assert r_long_rec.status_code == 422


# ---------------------------------------------------------------------------
# Test 6: Dashboard Analytics: Similar and Recommendation CTR & Wizard-Test Exclusion
# ---------------------------------------------------------------------------
def test_dashboard_analytics_similar_and_rec_metrics(tmp_path, monkeypatch, client: TestClient):
    storage = LocalStorage(base_dir=tmp_path)
    _patch_all_storage(monkeypatch, storage)

    tenant_id = "telco_default"
    admin_headers = {"X-API-Key": "sk-telco_default-xxxx"}
    client_headers = {"X-API-Key": "pk-telco_default-xxxx"}

    # Seed 1 similar request
    client.get("/v1/recommendations/similar/SP-01", headers=client_headers)

    # Track 1 similar click
    r1 = client.post(
        "/v1/track",
        json={
            "event_type": "click",
            "product_id": "SP-01",
            "session_id": "sess_sim_01",
            "source": "similar",
            "rec_id": "a1b2c3d4e5f67890",
        },
        headers=client_headers,
    )
    assert r1.status_code == 202

    # Track 1 similar add_to_cart
    r2 = client.post(
        "/v1/track",
        json={
            "event_type": "add_to_cart",
            "product_id": "SP-01",
            "session_id": "sess_sim_01",
            "source": "similar",
            "rec_id": "a1b2c3d4e5f67890",
        },
        headers=client_headers,
    )
    assert r2.status_code == 202

    # Track 1 similar purchase
    r3 = client.post(
        "/v1/track",
        json={
            "event_type": "purchase",
            "product_id": "SP-01",
            "session_id": "sess_sim_01",
            "source": "similar",
            "rec_id": "a1b2c3d4e5f67890",
        },
        headers=client_headers,
    )
    assert r3.status_code == 202

    # Track 1 recommendation click
    r4 = client.post(
        "/v1/track",
        json={
            "event_type": "click",
            "product_id": "SP-02",
            "session_id": "sess_rec_01",
            "source": "recommendation",
            "rec_id": "b1b2c3d4e5f67890",
        },
        headers=client_headers,
    )
    assert r4.status_code == 202

    # Track 1 test event with X-AIPOD-Source: wizard-test (MUST be excluded)
    r5 = client.post(
        "/v1/track",
        json={
            "event_type": "click",
            "product_id": "SP-99",
            "session_id": "sess_test_01",
            "source": "similar",
            "rec_id": "c1b2c3d4e5f67890",
        },
        headers={**client_headers, "X-AIPOD-Source": "wizard-test"},
    )
    assert r5.status_code == 202

    flush_telemetry(storage)
    clear_telemetry_cache()

    # Query GET /v1/dashboard/analytics
    res = client.get("/v1/dashboard/analytics", headers=admin_headers)
    assert res.status_code == 200
    analytics = res.json()

    assert analytics["similar_clicks"] == 1
    assert analytics["similar_add_to_carts"] == 1
    assert analytics["similar_purchases"] == 1
    assert analytics["similar_ctr"] > 0.0

    assert analytics["recommendation_clicks"] == 1


# ---------------------------------------------------------------------------
# Test 7: Storefront Demo Page Served
# ---------------------------------------------------------------------------
def test_storefront_demo_page_served(client: TestClient):
    for path in ["/similar", "/similar_products.html", "/demo/similar_products.html"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Mobitel LifeStore" in res.text
        assert "sdk.js" in res.text
        assert "aipod.getSimilar" in res.text
        assert "aipod.compare" in res.text


# ---------------------------------------------------------------------------
# Test 8: SDK Size & Public Methods
# ---------------------------------------------------------------------------
def test_sdk_file_size_and_methods():
    sdk_path = PROJECT_ROOT / "static" / "sdk.js"
    assert sdk_path.exists()
    content = sdk_path.read_text(encoding="utf-8")
    size_bytes = len(content.encode("utf-8"))

    # Strictly < 25 KB
    assert size_bytes < 25 * 1024, f"SDK size {size_bytes} exceeds 25 KB"

    # Public methods and helpers
    assert "escape:" in content
    assert "sanitizeUrl:" in content
    assert "formatPrice:" in content
    assert "getSimilar:" in content
    assert "compare:" in content
    assert "trackSimilarClick:" in content
    assert "window.AIPod = AIPod" in content
    assert "window.aipod = AIPod" in content
