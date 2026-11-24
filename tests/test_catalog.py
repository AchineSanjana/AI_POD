"""Comprehensive tests for tenant-managed product catalogue subsystem.

Verifies:
1. First-access auto-seeding from data/processed/{tenant}/products.csv.
2. Product CRUD (add, edit, soft delete, restore, permanent delete).
3. 409 Conflict on duplicate product_id.
4. 409 Conflict on concurrent modifications (optimistic concurrency version markers).
5. Multipart file upload preview and commit in both 'upsert' and 'replace' modes.
6. Upload validation and detailed row-level error reporting (with 1-indexed row numbers).
7. Snapshot creation, 10-snapshot retention pruning, and commit undo.
8. Server-side pagination, page_size clamping (max 100), and multi-field query filtering.
9. Strict authentication: public keys (pk-*) get 403 Forbidden, missing keys get 401.
10. Strict tenant isolation (no cross-tenant leakage).
11. CSV template download.
12. Full end-to-end catalogue lifecycle on mocked AWS S3 (via moto).
"""

from __future__ import annotations

import io
import json
import os
import secrets
import tempfile
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
from src.catalog.audit import get_catalog_history, record_catalog_audit
from src.catalog.service import (
    ConcurrentModificationError,
    DuplicateProductError,
    InvalidOperationError,
    ProductNotFoundError,
    SnapshotError,
    add_product,
    bulk_action,
    commit_upload,
    delete_product,
    ensure_catalog_exists,
    generate_catalog_template,
    get_catalog_summary,
    list_products,
    load_catalog,
    parse_and_preview_upload,
    restore_product,
    save_catalog,
    undo_last_commit,
    update_product,
)
from src.storage.local_storage import LocalStorage
from src.storage.s3_storage import S3Storage


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Ensure clean rate limits between tests."""
    RATE_LIMITER.reset()
    yield
    RATE_LIMITER.reset()


@pytest.fixture(autouse=True)
def setup_auth_and_env(monkeypatch):
    """Ensure test environment and API key mappings are properly loaded."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AI_POD_ENV", "development")
    load_tenant_auth()
    # Register test tenant keys
    for t in ("e2e_tenant_cat_a", "e2e_tenant_cat_b", "e2e_tenant_s3"):
        TENANT_KEY_RECORDS[f"sk-{t}-xxxx"] = {"tenant_id": t, "key_type": "private", "created_at": None}
        TENANT_AUTH_MAPPING[f"sk-{t}-xxxx"] = t
        TENANT_KEY_RECORDS[f"pk-{t}-xxxx"] = {"tenant_id": t, "key_type": "public", "created_at": None}
        TENANT_AUTH_MAPPING[f"pk-{t}-xxxx"] = t
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Seeding from products.csv
# ---------------------------------------------------------------------------

def test_seeding_from_products_csv_on_first_access(tmp_path):
    storage = LocalStorage(base_dir=tmp_path)
    tenant_id = "e2e_tenant_seed_test"

    # Create dummy data/processed/{tenant}/products.csv
    proc_path = f"data/processed/{tenant_id}/products.csv"
    proc_df = pd.DataFrame(
        [
            {"product_id": "P101", "product_name": "Laptop Pro", "category": "Computers", "price": 1299.0},
            {"product_id": "P102", "title": "Wireless Mouse", "price": 29.99},  # test title fallback & default category
        ]
    )
    storage.write_file(proc_path, proc_df.to_csv(index=False).encode("utf-8"))

    # Ensure catalog.csv does not exist yet
    cat_path = f"data/catalog/{tenant_id}/catalog.csv"
    assert not storage.exists(cat_path)

    # First access loads and auto-seeds
    df, version = ensure_catalog_exists(tenant_id, storage=storage, who="test_seeder")
    assert storage.exists(cat_path)
    assert len(df) == 2
    assert version is not None

    # Verify column defaults
    p102 = df[df["product_id"] == "P102"].iloc[0]
    assert p102["product_name"] == "Wireless Mouse"
    assert p102["category"] == "General"
    assert p102["status"] == "active"
    assert int(p102["in_stock"]) == 1

    # Verify audit record created for seeding
    history = get_catalog_history(tenant_id, limit=10, storage=storage)
    assert len(history) == 1
    assert history[0]["action"] == "seed"
    assert history[0]["product_ids_count"] == 2


# ---------------------------------------------------------------------------
# 2. Product Add & Duplicate 409
# ---------------------------------------------------------------------------

def test_add_product_and_duplicate_409(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    # Add valid product
    payload = {
        "product_id": "PROD-100",
        "product_name": "Noise Cancelling Headphones",
        "category": "Audio",
        "brand": "SoundWave",
        "price": 149.99,
        "in_stock": 1,
        "description": "High fidelity audio",
        "custom_color": "matte_black",  # pass-through attribute
    }
    resp = client.post("/v1/catalog/products", json=payload, headers=headers)
    assert resp.status_code == 201
    created = resp.json()
    assert created["product_id"] == "PROD-100"
    assert created["status"] == "active"
    assert created["custom_color"] == "matte_black"
    assert created["price"] == 149.99

    # Duplicate product_id returns 409
    dup_resp = client.post("/v1/catalog/products", json=payload, headers=headers)
    assert dup_resp.status_code == 409
    assert "already exists" in dup_resp.json()["detail"]

    # Validation errors return 400
    bad_price_payload = dict(payload, product_id="PROD-101", price=-10.0)
    bad_resp = client.post("/v1/catalog/products", json=bad_price_payload, headers=headers)
    assert bad_resp.status_code == 422 or bad_resp.status_code == 400

    empty_id_payload = dict(payload, product_id="")
    empty_resp = client.post("/v1/catalog/products", json=empty_id_payload, headers=headers)
    assert empty_resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# 3. Product Edit / Patch
# ---------------------------------------------------------------------------

def test_patch_product(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    client.post(
        "/v1/catalog/products",
        json={"product_id": "P200", "product_name": "Old Name", "category": "Tech", "price": 50.0},
        headers=headers,
    )

    # Patch fields
    patch_resp = client.patch(
        "/v1/catalog/products/P200",
        json={"product_name": "Updated Name", "price": 79.99, "brand": "NewBrand"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["product_name"] == "Updated Name"
    assert updated["price"] == 79.99
    assert updated["brand"] == "NewBrand"
    assert updated["category"] == "Tech"  # preserved

    # Patch non-existent product
    nf_resp = client.patch(
        "/v1/catalog/products/NONEXISTENT",
        json={"product_name": "Foo"},
        headers=headers,
    )
    assert nf_resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Soft Delete (Archive), Restore, and Permanent Delete
# ---------------------------------------------------------------------------

def test_archive_restore_and_permanent_delete(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    client.post(
        "/v1/catalog/products",
        json={"product_id": "P300", "product_name": "Chair", "category": "Furniture"},
        headers=headers,
    )

    # 1. Attempt permanent delete on active product -> 400 Bad Request
    perm_fail = client.delete("/v1/catalog/products/P300?permanent=true", headers=headers)
    assert perm_fail.status_code == 400
    assert "Only already-archived products can be permanently deleted" in perm_fail.json()["detail"]

    # 2. Soft delete (archive)
    soft_resp = client.delete("/v1/catalog/products/P300", headers=headers)
    assert soft_resp.status_code == 200
    assert soft_resp.json()["status"] == "archived"

    # Verify summary shows 1 archived, 0 active
    summary = client.get("/v1/catalog/summary", headers=headers).json()
    assert summary["archived"] == 1
    assert summary["active"] == 0

    # 3. Restore product
    restore_resp = client.post("/v1/catalog/products/P300/restore", headers=headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["status"] == "active"

    summary_after = client.get("/v1/catalog/summary", headers=headers).json()
    assert summary_after["active"] == 1
    assert summary_after["archived"] == 0

    # 4. Archive again, then permanently delete
    client.delete("/v1/catalog/products/P300", headers=headers)
    perm_ok = client.delete("/v1/catalog/products/P300?permanent=true", headers=headers)
    assert perm_ok.status_code == 200
    assert perm_ok.json()["status"] == "deleted"

    # Product should now be gone
    get_resp = client.patch("/v1/catalog/products/P300", json={"price": 10}, headers=headers)
    assert get_resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Bulk Mutations
# ---------------------------------------------------------------------------

def test_bulk_mutations(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    for i in range(1, 4):
        client.post(
            "/v1/catalog/products",
            json={"product_id": f"BULK-{i}", "product_name": f"Item {i}", "category": "Batch"},
            headers=headers,
        )

    # Bulk archive
    arch_resp = client.post(
        "/v1/catalog/bulk",
        json={"action": "archive", "product_ids": ["BULK-1", "BULK-2"]},
        headers=headers,
    )
    assert arch_resp.status_code == 200
    assert arch_resp.json()["affected"] == 2

    summary = client.get("/v1/catalog/summary", headers=headers).json()
    assert summary["archived"] == 2
    assert summary["active"] == 1

    # Bulk restore
    rest_resp = client.post(
        "/v1/catalog/bulk",
        json={"action": "restore", "product_ids": ["BULK-1"]},
        headers=headers,
    )
    assert rest_resp.status_code == 200
    assert rest_resp.json()["affected"] == 1

    summary2 = client.get("/v1/catalog/summary", headers=headers).json()
    assert summary2["active"] == 2
    assert summary2["archived"] == 1

    # Bulk delete (only deletes already-archived BULK-2, skips active BULK-1)
    del_resp = client.post(
        "/v1/catalog/bulk",
        json={"action": "delete", "product_ids": ["BULK-1", "BULK-2"]},
        headers=headers,
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["affected"] == 1
    assert "BULK-2" in del_resp.json()["product_ids"]

    # Over 500 IDs returns 400
    too_many = [f"ID-{n}" for n in range(501)]
    over_resp = client.post(
        "/v1/catalog/bulk",
        json={"action": "archive", "product_ids": too_many},
        headers=headers,
    )
    assert over_resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# 6. Optimistic Concurrency 409
# ---------------------------------------------------------------------------

def test_concurrent_edit_conflict_409(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    # Add initial product
    client.post(
        "/v1/catalog/products",
        json={"product_id": "P_CONC", "product_name": "Concurrent Test", "category": "Tests"},
        headers=headers,
    )

    # Read products and get initial ETag / version marker
    get_res = client.get("/v1/catalog/products", headers=headers)
    initial_version = get_res.headers.get("X-Catalog-Version")
    assert initial_version is not None

    # Worker A updates the product successfully
    patch_a = client.patch(
        "/v1/catalog/products/P_CONC",
        json={"price": 10.0},
        headers={**headers, "If-Match": initial_version},
    )
    assert patch_a.status_code == 200

    # Worker B tries to update using the stale initial_version -> 409 Conflict
    patch_b = client.patch(
        "/v1/catalog/products/P_CONC",
        json={"price": 20.0},
        headers={**headers, "If-Match": initial_version},
    )
    assert patch_b.status_code == 409
    assert "concurrently" in patch_b.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 7. Upload Preview and Commit in Both Modes (Upsert & Replace)
# ---------------------------------------------------------------------------

def test_upload_preview_and_commit_both_modes(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    # Seed with P1 and P2
    client.post(
        "/v1/catalog/products",
        json={"product_id": "P1", "product_name": "Product 1", "category": "CatA", "price": 10.0},
        headers=headers,
    )
    client.post(
        "/v1/catalog/products",
        json={"product_id": "P2", "product_name": "Product 2", "category": "CatA", "price": 20.0},
        headers=headers,
    )

    # --- Mode 1: Upsert Mode ---
    # Upload file with P2 (update) and P3 (new)
    csv_upsert = "product_id,product_name,category,price\nP2,Product 2 Updated,CatA,25.0\nP3,Product 3,CatB,30.0\n"
    preview_upsert = client.post(
        "/v1/catalog/upload",
        data={"mode": "upsert"},
        files={"file": ("upload.csv", csv_upsert.encode("utf-8"), "text/csv")},
        headers=headers,
    )
    assert preview_upsert.status_code == 200
    p_up_data = preview_upsert.json()
    assert p_up_data["to_add"] == 1  # P3
    assert p_up_data["to_update"] == 1  # P2
    assert p_up_data["to_archive"] == 0
    assert p_up_data["errors"] == []
    upload_id_1 = p_up_data["upload_id"]

    # Verify P3 is not in catalog yet before commit
    check_before = client.get("/v1/catalog/products?query=P3", headers=headers).json()
    assert check_before["total"] == 0

    # Commit upsert
    commit_1 = client.post(f"/v1/catalog/upload/{upload_id_1}/commit", headers=headers)
    assert commit_1.status_code == 200
    assert commit_1.json()["status"] == "committed"
    assert commit_1.json()["added"] == 1
    assert commit_1.json()["updated"] == 1

    # Verify all 3 products are active
    sum_1 = client.get("/v1/catalog/summary", headers=headers).json()
    assert sum_1["active"] == 3

    # --- Mode 2: Replace Mode ---
    # Upload file containing only P3 (update) and P4 (new). Active P1 and P2 are MISSING -> should be archived!
    csv_replace = "product_id,product_name,category,price\nP3,Product 3 Replaced,CatB,35.0\nP4,Product 4,CatC,40.0\n"
    preview_replace = client.post(
        "/v1/catalog/upload",
        data={"mode": "replace"},
        files={"file": ("upload_rep.csv", csv_replace.encode("utf-8"), "text/csv")},
        headers=headers,
    )
    assert preview_replace.status_code == 200
    p_rep_data = preview_replace.json()
    assert p_rep_data["to_add"] == 1  # P4
    assert p_rep_data["to_update"] == 1  # P3
    assert p_rep_data["to_archive"] == 2  # P1, P2
    upload_id_2 = p_rep_data["upload_id"]

    # Commit replace
    commit_2 = client.post(f"/v1/catalog/upload/{upload_id_2}/commit", headers=headers)
    assert commit_2.status_code == 200
    c2_data = commit_2.json()
    assert c2_data["archived"] == 2  # P1 and P2 archived
    assert c2_data["added"] == 1
    assert c2_data["updated"] == 1

    # Summary: 2 active (P3, P4) and 2 archived (P1, P2)
    sum_2 = client.get("/v1/catalog/summary", headers=headers).json()
    assert sum_2["active"] == 2
    assert sum_2["archived"] == 2


# ---------------------------------------------------------------------------
# 8. Upload Validation: Bad Rows Reported with Row Numbers
# ---------------------------------------------------------------------------

def test_upload_bad_rows_reported_with_row_numbers(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    # Row 1: Header
    # Row 2: Valid
    # Row 3: Missing category
    # Row 4: Negative price
    # Row 5: Duplicate ID (same as Row 2)
    # Row 6: Empty product_id
    bad_csv = (
        "product_id,product_name,category,price\n"
        "VAL-1,Valid Product,Tech,19.99\n"
        "VAL-2,Missing Cat,,29.99\n"
        "VAL-3,Bad Price,Tech,-5.0\n"
        "VAL-1,Duplicate Val,Tech,19.99\n"
        ",No ID,Tech,10.0\n"
    )

    resp = client.post(
        "/v1/catalog/upload",
        files={"file": ("errors.csv", bad_csv.encode("utf-8"), "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200
    errors = resp.json()["errors"]
    assert len(errors) >= 4

    error_map = {e["row"]: e["message"] for e in errors}
    assert 3 in error_map
    assert "category" in error_map[3].lower()

    assert 4 in error_map
    assert "price" in error_map[4].lower()

    assert 5 in error_map
    assert "duplicate" in error_map[5].lower()

    assert 6 in error_map
    assert "product_id" in error_map[6].lower()


# ---------------------------------------------------------------------------
# 9. Snapshot Undo & Retention Pruning
# ---------------------------------------------------------------------------

def test_undo_and_snapshots(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    # Initial state: 1 item
    client.post(
        "/v1/catalog/products",
        json={"product_id": "BASE-1", "product_name": "Base Product", "category": "General"},
        headers=headers,
    )

    # Calling undo when no commit has occurred returns 400
    undo_fail = client.post("/v1/catalog/undo", headers=headers)
    assert undo_fail.status_code == 400
    assert "No snapshot available" in undo_fail.json()["detail"]

    # Upload & Commit 2 new items
    upload_csv = "product_id,product_name,category\nADD-1,Item 1,Cat\nADD-2,Item 2,Cat\n"
    p_resp = client.post(
        "/v1/catalog/upload",
        files={"file": ("snap.csv", upload_csv.encode("utf-8"), "text/csv")},
        headers=headers,
    ).json()
    client.post(f"/v1/catalog/upload/{p_resp['upload_id']}/commit", headers=headers)

    # Verify 3 items now
    assert client.get("/v1/catalog/summary", headers=headers).json()["active"] == 3

    # Undo commit: should restore to 1 item
    undo_resp = client.post("/v1/catalog/undo", headers=headers)
    assert undo_resp.status_code == 200
    assert undo_resp.json()["status"] == "restored"
    assert undo_resp.json()["total_products"] == 1

    # Verify catalog is back to 1 item
    summary_after = client.get("/v1/catalog/summary", headers=headers).json()
    assert summary_after["active"] == 1

    # History shows undo action
    history = client.get("/v1/catalog/history", headers=headers).json()["changes"]
    assert history[0]["action"] == "undo"


# ---------------------------------------------------------------------------
# 10. Server-Side Pagination & Query Filtering
# ---------------------------------------------------------------------------

def test_pagination_and_query_filters(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    # Seed 25 items across categories
    items = []
    for i in range(1, 26):
        cat = "Electronics" if i <= 15 else "Books"
        items.append(
            {
                "product_id": f"ITEM-{i:03d}",
                "product_name": f"Product {i}",
                "category": cat,
                "brand": "BrandX" if i % 2 == 0 else "BrandY",
                "price": float(i * 10),
            }
        )
    for it in items:
        client.post("/v1/catalog/products", json=it, headers=headers)

    # Page 1 with page_size=10
    p1 = client.get("/v1/catalog/products?page=1&page_size=10", headers=headers).json()
    assert p1["total"] == 25
    assert len(p1["items"]) == 10
    assert p1["page"] == 1
    assert p1["total_pages"] == 3

    # Page 3 with page_size=10 (last 5 items)
    p3 = client.get("/v1/catalog/products?page=3&page_size=10", headers=headers).json()
    assert len(p3["items"]) == 5

    # page_size clamped to max 100
    p_clamped = client.get("/v1/catalog/products?page=1&page_size=150", headers=headers)
    assert p_clamped.status_code in (200, 422)
    if p_clamped.status_code == 200:
        assert p_clamped.json()["page_size"] <= 100

    # Filter by category
    books = client.get("/v1/catalog/products?category=Books", headers=headers).json()
    assert books["total"] == 10

    # Query search (matching brand)
    brand_x = client.get("/v1/catalog/products?query=BrandX", headers=headers).json()
    assert brand_x["total"] == 12


# ---------------------------------------------------------------------------
# 11. Authentication & Tenant Isolation
# ---------------------------------------------------------------------------

def test_auth_public_key_403_and_tenant_isolation(client, tmp_path, monkeypatch):
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant_a = "e2e_tenant_cat_a"
    tenant_b = "e2e_tenant_cat_b"

    # Public key (pk-*) rejected with 403 Forbidden
    pk_headers = {"X-API-Key": f"pk-{tenant_a}-xxxx"}
    forbidden_resp = client.get("/v1/catalog/products", headers=pk_headers)
    assert forbidden_resp.status_code == 403

    # Missing API key rejected with 401
    unauth_resp = client.get("/v1/catalog/products")
    assert unauth_resp.status_code == 401

    # Tenant Isolation: add product in Tenant A
    sk_a = {"X-API-Key": f"sk-{tenant_a}-xxxx"}
    client.post(
        "/v1/catalog/products",
        json={"product_id": "SECRET_A", "product_name": "Tenant A Secret", "category": "Confidential"},
        headers=sk_a,
    )

    # Tenant B should see an empty catalogue
    sk_b = {"X-API-Key": f"sk-{tenant_b}-xxxx"}
    res_b = client.get("/v1/catalog/products", headers=sk_b).json()
    assert res_b["total"] == 0

    # Tenant B cannot patch Tenant A's product
    patch_b = client.patch(
        "/v1/catalog/products/SECRET_A",
        json={"price": 99.0},
        headers=sk_b,
    )
    assert patch_b.status_code == 404


# ---------------------------------------------------------------------------
# 12. Template Download
# ---------------------------------------------------------------------------

def test_template_download(client):
    headers = {"X-API-Key": "sk-e2e_tenant_cat_a-xxxx"}
    resp = client.get("/v1/catalog/template?format=csv", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "product_id,product_name,category" in resp.text
    assert "PROD-001" in resp.text

    # Unsupported format
    bad_fmt = client.get("/v1/catalog/template?format=pdf", headers=headers)
    assert bad_fmt.status_code == 400


# ---------------------------------------------------------------------------
# 13. Full Catalogue Lifecycle on Mocked AWS S3
# ---------------------------------------------------------------------------

@mock_aws
def test_full_catalogue_lifecycle_mocked_s3(monkeypatch):
    """Verify entire catalogue lifecycle with S3Storage backend using moto."""
    # Setup AWS Credentials & S3 bucket
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket="mock-ai-pod-bucket")

    storage = S3Storage(bucket_name="mock-ai-pod-bucket", s3_client=s3_client)
    tenant_id = "e2e_tenant_s3"

    # 1. First-access empty init
    df, v1 = ensure_catalog_exists(tenant_id, storage=storage, who="s3_tester")
    assert df.empty
    assert storage.exists(f"data/catalog/{tenant_id}/catalog.csv")
    assert v1 is not None

    # 2. Add product
    prod = add_product(
        tenant_id=tenant_id,
        data={"product_id": "S3-100", "product_name": "Cloud Storage Widget", "category": "Cloud", "price": 49.0},
        who="s3_tester",
        storage=storage,
    )
    assert prod["product_id"] == "S3-100"

    # 3. Update product
    updated = update_product(
        tenant_id=tenant_id,
        product_id="S3-100",
        update_data={"price": 59.99},
        who="s3_tester",
        storage=storage,
    )
    assert updated["price"] == 59.99

    # 4. Upload Preview & Commit in Replace Mode
    upload_csv = "product_id,product_name,category,price\nS3-200,New Cloud Item,Cloud,99.0\n"
    preview = parse_and_preview_upload(
        tenant_id=tenant_id,
        file_bytes=upload_csv.encode("utf-8"),
        filename="s3_upload.csv",
        mode="replace",
        storage=storage,
    )
    assert preview["to_add"] == 1
    assert preview["to_archive"] == 1  # S3-100 archived

    commit_res = commit_upload(
        tenant_id=tenant_id,
        upload_id=preview["upload_id"],
        who="s3_tester",
        storage=storage,
    )
    assert commit_res["archived"] == 1
    assert commit_res["added"] == 1

    # 5. Verify summary
    summary = get_catalog_summary(tenant_id=tenant_id, storage=storage)
    assert summary["active"] == 1
    assert summary["archived"] == 1

    # 6. Verify pre-commit snapshot was created in S3
    snapshots = storage.list_files(f"data/catalog/{tenant_id}/snapshots/")
    assert len(snapshots) >= 1

    # 7. Undo commit
    undo_res = undo_last_commit(tenant_id=tenant_id, who="s3_tester", storage=storage)
    assert undo_res["status"] == "restored"

    # Catalog is back to 1 active (S3-100)
    summary_after = get_catalog_summary(tenant_id=tenant_id, storage=storage)
    assert summary_after["active"] == 1
    assert summary_after["archived"] == 0

    # 8. Check audit log part files in S3
    audit_files = storage.list_files(f"data/catalog/{tenant_id}/audit/")
    assert len(audit_files) >= 4  # seed, create, update, upload_commit, undo
    history = get_catalog_history(tenant_id=tenant_id, limit=20, storage=storage)
    assert len(history) >= 4
    assert history[0]["action"] == "undo"


def test_snapshot_pruning_to_10(client, tmp_path, monkeypatch):
    """Verify pre-commit snapshot pruning retains at most the last 10 snapshots."""
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    # Commit 12 successive uploads
    for i in range(1, 13):
        upload_csv = f"product_id,product_name,category\nP_{i},Product {i},Cat\n"
        p_resp = client.post(
            "/v1/catalog/upload",
            files={"file": (f"up_{i}.csv", upload_csv.encode("utf-8"), "text/csv")},
            headers=headers,
        ).json()
        commit_res = client.post(f"/v1/catalog/upload/{p_resp['upload_id']}/commit", headers=headers)
        assert commit_res.status_code == 200

    # Verify at most 10 snapshot files are retained
    snapshots = storage.list_files(f"data/catalog/{tenant}/snapshots/")
    assert len(snapshots) <= 10


def test_audit_log_contains_no_secrets(client, tmp_path, monkeypatch):
    """Confirm audit log stores safe actor metadata and NEVER raw secret keys, JWTs, or passwords."""
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    secret_key = f"sk-{tenant}-xxxx"
    headers = {"X-API-Key": secret_key}

    # Add a product to trigger audit logging
    client.post(
        "/v1/catalog/products",
        json={"product_id": "SEC-01", "product_name": "Audit Security Check", "category": "Security"},
        headers=headers,
    )

    # Inspect all audit files
    audit_files = storage.list_files(f"data/catalog/{tenant}/audit/")
    assert len(audit_files) > 0

    for af in audit_files:
        raw_text = storage.read_file(af).decode("utf-8")
        # Ensure secret_key never appears in plaintext
        assert secret_key not in raw_text
        assert "password" not in raw_text.lower()
        # Verify who field matches safe pattern
        entry = json.loads(raw_text.strip().splitlines()[-1])
        assert entry["who"] == f"tenant:{tenant}:private_key"


def test_undo_when_no_snapshot_exists_returns_friendly_message(client, tmp_path, monkeypatch):
    """Ensure calling /v1/catalog/undo when no snapshots exist returns a clean HTTP 400 with friendly message."""
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    headers = {"X-API-Key": f"sk-{tenant}-xxxx"}

    resp = client.post("/v1/catalog/undo", headers=headers)
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data
    assert data["detail"] == "No snapshot available to undo."


def test_cors_preflight_catalogue_and_recommendations_routes(client):
    """Verify CORS preflight OPTIONS allows all frontend/SDK headers for catalogue and recommendations routes."""
    origin = "http://localhost:5173"
    request_headers = [
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Session-Token",
        "X-AIPOD-Source",
        "If-Match",
        "X-Catalog-Version",
    ]
    req_headers_str = ", ".join(request_headers)

    for route in ("/v1/catalog/products", "/v1/recommendations"):
        resp = client.options(
            route,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": req_headers_str,
            },
        )
        assert resp.status_code == 200, f"Preflight failed for {route}: {resp.status_code}"
        assert resp.headers.get("access-control-allow-origin") == origin
        assert resp.headers.get("access-control-allow-credentials") is None or resp.headers.get("access-control-allow-credentials") == "false"
        allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
        if allow_headers != "*":
            for h in request_headers:
                assert h.lower() in allow_headers, f"Header {h} not permitted in Access-Control-Allow-Headers on {route}"


def test_cors_get_response_exposes_etag_and_catalog_version(client, tmp_path, monkeypatch):
    """Verify normal GET responses expose ETag and X-Catalog-Version in Access-Control-Expose-Headers."""
    from src.storage import get_storage_backend
    storage = LocalStorage(base_dir=tmp_path)
    monkeypatch.setattr("src.catalog.service.get_storage_backend", lambda cfg=None: storage)
    monkeypatch.setattr("src.catalog.audit.get_storage_backend", lambda cfg=None: storage)

    tenant = "e2e_tenant_cat_a"
    origin = "http://localhost:5173"
    headers = {
        "X-API-Key": f"sk-{tenant}-xxxx",
        "Origin": origin,
    }

    # 1. Products list
    resp_prod = client.get("/v1/catalog/products", headers=headers)
    assert resp_prod.status_code == 200
    assert resp_prod.headers.get("access-control-allow-origin") == origin
    expose_headers_prod = resp_prod.headers.get("access-control-expose-headers", "").lower()
    assert "etag" in expose_headers_prod
    assert "x-catalog-version" in expose_headers_prod
    assert "etag" in resp_prod.headers or "ETag" in resp_prod.headers
    assert "x-catalog-version" in resp_prod.headers or "X-Catalog-Version" in resp_prod.headers

    # 2. Summary
    resp_sum = client.get("/v1/catalog/summary", headers=headers)
    assert resp_sum.status_code == 200
    expose_headers_sum = resp_sum.headers.get("access-control-expose-headers", "").lower()
    assert "etag" in expose_headers_sum
    assert "x-catalog-version" in expose_headers_sum
    assert "etag" in resp_sum.headers or "ETag" in resp_sum.headers
    assert "x-catalog-version" in resp_sum.headers or "X-Catalog-Version" in resp_sum.headers



