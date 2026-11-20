# Change Document: Tenant-Managed Product Catalogue (Step C1)

**Date:** 2026-11-20  
**Status:** Completed  
**Scope:** Sovereign tenant-managed product catalogue, atomic storage persistence (`data/catalog/{tenant_id}/catalog.csv`), version-marker optimistic concurrency, first-access auto-seeding, soft deletion lifecycle, multipart batch uploads with preview/commit and snapshots, multi-worker and S3-safe audit part-file logging, snapshot undo, and 12 administrative endpoints under `/v1/catalog/*`.

---

## 1. Step 0 Findings & Architectural Analysis

### A. Prior Context Review (Steps 05 & 06)
- **Step 05 (`docs/changes/05_recommendations.md`):** Unified model artifact storage on `models/{tenant_id}/final_model.joblib`, introduced cold-start diagnostics (`reason`), chunked range-reading for sample customers, zero-restart hot reloading, and strict multi-tenant isolation.
- **Step 06 (`docs/changes/06_dashboard.md`):** Eliminated all mock/hardcoded values from admin dashboards, established multi-worker and S3-safe telemetry logging via collision-proof part files (`data/telemetry/{tenant_id}/{YYYY-MM-DD}/part-*.jsonl`), and secured admin endpoints via `get_tenant_for_admin_action`.

### B. Analysis of Existing Catalog & Feed Modules
- **`src/catalog/feed_parser.py`:** Parses Google Shopping RSS 2.0 / Atom XML feeds and JSON product feeds (arrays or objects with `products`/`items`). Standardizes fields into `product_id`, `product_name`, `price` (cleaned via regex float extraction in `_clean_price`), and `category`.
- **`src/catalog/feed_sync.py`:** Synchronizes external feeds or platform connections (e.g., Shopify) directly into `data/processed/{tenant_id}/products.csv` using pandas merges and deduplication.
- **`src/core/schema.py` (`ProductSchema`):** Defines the data contract for product dataframes used in recommendation models. Requires `product_id` (primary key), feature specifications, and category (if declared). `product_name` is recognized as an optional display column. `validate()` checks required columns, while `validate_values()` validates numeric types and categorical allowed values.

### C. How `products.csv` is Currently Produced
In `src/pipeline/run.py` (lines 119–155):
```python
adapter = GenericConfigAdapter(tenant_cfg, storage=storage)
customers, products, interactions = adapter.run()
...
prefix_data = f"data/processed/{tenant_id}"
storage.write_file(
    f"{prefix_data}/products.csv",
    products.to_csv(index=False).encode("utf-8"),
)
```
1. `run_tenant_pipeline` instantiates `GenericConfigAdapter(tenant_cfg, storage=storage)`.
2. `adapter.run()` calls `to_products()`:
   - If `tenant_config.products.derived_from == "transactional"`, products are derived on the fly from the raw transactional log (`derive_products_from_transactional`).
   - If `derived_from == "interaction_source"`, products are derived via `derive_products_from_interaction_source`.
   - Otherwise, raw input tables are copied directly.
3. The resulting DataFrame is validated against `ProductSchema` and written directly to:
   ```
   data/processed/{tenant_id}/products.csv
   ```

### D. Overwrite Analysis: Would a Retrain Overwrite Catalogue Edits?
**YES. Prior to Step C1, any retrain completely overwrote catalogue edits.**
- **The Problem:** In the original pipeline architecture, `data/processed/{tenant_id}/products.csv` was treated as a transient build artifact derived directly from raw ingestion data. Whenever a scheduled retrain (`scripts/run_scheduled_retrain.py`), manual retrain (`POST /v1/onboard/train`), or background job executed `run_tenant_pipeline`, `adapter.run()` re-derived products from raw inputs and unconditionally overwrote `data/processed/{tenant_id}/products.csv`. Any manual edits, additions, or status changes were wiped out.
- **The Solution in Step C1:** Establish an authoritative, sovereign catalog location:
  ```
  data/catalog/{tenant_id}/catalog.csv
  ```
  Managed by the tenant through dedicated CRUD and batch upload endpoints. This file is decoupled from raw ingestion data and serves as the permanent Source of Truth.

---

## 2. Files Created and Modified

| File | Type | Description |
| :--- | :--- | :--- |
| `src/catalog/service.py` | Created | Core service layer: optimistic concurrency via version markers, auto-seeding from `products.csv`, CRUD, soft/permanent delete lifecycle, bulk mutations (max 500), XLSX/JSON/CSV preview parsing, snapshotting, and undo. |
| `src/catalog/audit.py` | Created | S3- and multi-worker safe audit logging writing isolated part files under `data/catalog/{tenant}/audit/{date}/part-*.jsonl`; history retrieval of last 50 changes; safe actor resolution (never leaks secrets). |
| `src/catalog/__init__.py` | Modified | Clean package exports of catalog service, parser, and audit functions. |
| `src/api/catalog.py` | Created | FastAPI APIRouter implementing all 12 endpoints under `/v1/catalog/*`, rate limited via `check_rate_limit(scope="catalog")` and protected by `get_tenant_for_admin_action`. |
| `src/api/schemas.py` | Modified | Pydantic request and response models for catalog management, supporting pass-through custom attributes (`extra="allow"`). |
| `src/api/app.py` | Modified | Mounted `catalog_router` on `v1_router` (`/v1/catalog/*`) and root router (`/catalog/*`). |
| `tests/test_catalog.py` | Created | 15 comprehensive unit and integration tests covering CRUD, optimistic concurrency, seeding, upload preview/commit, bad row numbering, snapshots, pagination, auth, tenant isolation, mocked S3 (moto), and secret leakage prevention. |
| `scripts/live_check_c1.py` | Created | Automated live end-to-end verification script exercising the running uvicorn server with a throwaway test tenant. |
| `docs/changes/07_catalog.md` | Modified | Complete architecture documentation, verification results, and operational runbook. |

---

## 3. Endpoints Verification Checklist

Programmatically verified against `app.openapi()['paths']`:

| Method | Path | Status | Verification Detail |
| :--- | :--- | :--- | :--- |
| `GET` | `/v1/catalog/products` | **IMPLEMENTED** | Server-side paginated catalogue search, category & status filters, returns `ETag` and `X-Catalog-Version`. |
| `GET` | `/v1/catalog/summary` | **IMPLEMENTED** | Counts for active, archived, out of stock, by category, and added since last training. |
| `POST` | `/v1/catalog/products` | **IMPLEMENTED** | Add single product; returns HTTP 409 Conflict if `product_id` already exists. |
| `PATCH` | `/v1/catalog/products/{product_id}` | **IMPLEMENTED** | Partial update of fields; returns 409 on version marker mismatch. |
| `DELETE` | `/v1/catalog/products/{product_id}` | **IMPLEMENTED** | Soft delete (`status=archived`). Permanent delete only with `?permanent=true` and only on already-archived items. |
| `POST` | `/v1/catalog/products/{product_id}/restore` | **IMPLEMENTED** | Restores archived product to `active` status. |
| `POST` | `/v1/catalog/bulk` | **IMPLEMENTED** | Bulk action (`archive`, `restore`, `delete`) on up to 500 product IDs. |
| `GET` | `/v1/catalog/template` | **IMPLEMENTED** | Returns CSV template (`?format=csv`) with standard headers and sample row. |
| `POST` | `/v1/catalog/upload` | **IMPLEMENTED** | Multipart file upload preview (CSV, JSON, XLSX <=20MB, max 100k rows) with row-numbered errors and diff counts. |
| `POST` | `/v1/catalog/upload/{upload_id}/commit` | **IMPLEMENTED** | Commits pending upload, takes pre-commit snapshot, archives missing items in replace mode (never hard deletes). |
| `GET` | `/v1/catalog/history` | **IMPLEMENTED** | Returns last 50 audit changes sorted newest first from part files. |
| `POST` | `/v1/catalog/undo` | **IMPLEMENTED** | Restores pre-commit snapshot taken before last commit; retains at most 10 snapshots. |

---

## 4. Feature Implementation & Code References

| Feature | Status | Implementation Reference |
| :--- | :--- | :--- |
| **Source of Truth** | **IMPLEMENTED** | `src/catalog/service.py:87-90, 311-329` (`data/catalog/{tenant_id}/catalog.csv` written atomically via `StorageBackend`). |
| **First-Access Seeding** | **IMPLEMENTED** | `src/catalog/service.py:136-235` (`ensure_catalog_exists` maps `products.csv` to standard schema with status=`active`, fallback names/categories). |
| **Optimistic Concurrency** | **IMPLEMENTED** | `src/catalog/service.py:314-320` (`storage.get_version_marker` compared against `expected_version`, raises `ConcurrentModificationError` -> HTTP 409). |
| **Soft Delete & Permanent Delete** | **IMPLEMENTED** | `src/catalog/service.py:640-702` (soft delete sets `status="archived"`; `permanent=True` rejected with HTTP 400 unless `status=="archived"`). |
| **Upload Preview & Validation** | **IMPLEMENTED** | `src/catalog/service.py:903-1080` (enforces 20MB limit, 100k row limit, trimmed IDs, non-negative price, 1-indexed row-numbered error reporting). |
| **Upload Commit & Retention** | **IMPLEMENTED** | `src/catalog/service.py:1083-1224` (creates `snapshot-{ts}-{upload_id}.csv`, prunes snapshots to 10; replace mode archives missing active products). |
| **Pending Upload Expiration** | **IMPLEMENTED** | `src/catalog/service.py:1049-1052, 1098-1102` (pending uploads expire after 3600s / 1 hour). |
| **Snapshot Undo** | **IMPLEMENTED** | `src/catalog/service.py:1226-1269` (`undo_last_commit` restores latest snapshot and records `action="undo"`). |
| **Audit Part Files** | **IMPLEMENTED** | `src/catalog/audit.py:46-72` (`data/catalog/{tenant}/audit/{YYYY-MM-DD}/part-{ts}-{pid}-{rand}.jsonl`). |
| **Audit Secrets Safety** | **IMPLEMENTED** | `src/api/catalog.py:82-120` (`_resolve_actor` records `account:<id>` or `tenant:<id>:<key_type>_key`; never logs raw keys, JWTs, or passwords). |
| **Page Size Clamped to 100** | **IMPLEMENTED** | `src/catalog/service.py:399` (`page_size = max(1, min(100, page_size))`) and `src/api/catalog.py:133` (`le=100`). |
| **Bulk Mutation Limit (500)** | **IMPLEMENTED** | `src/catalog/service.py:757-759` (`len(clean_ids) > 500` raises `ValueError` -> HTTP 400). |
| **Authentication & Tenant Isolation** | **IMPLEMENTED** | `src/api/auth.py:293-384` (`get_tenant_for_admin_action` rejects `pk-` keys with 403, derives tenant strictly from credentials). |
| **Rate Limiting** | **IMPLEMENTED** | `src/api/catalog.py:76-78` (`check_rate_limit(scope="catalog", tenant_dep=get_tenant_for_admin_action)`). |

---

## 5. Test Results

### A. Catalog Test Suite (`tests/test_catalog.py`)
Executed via: `pytest tests/test_catalog.py -v`
```
============================= test session starts =============================
platform win32 -- Python 3.11.1, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\Projects\AI_POD
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 15 items

tests/test_catalog.py::test_seeding_from_products_csv_on_first_access PASSED [  6%]
tests/test_catalog.py::test_add_product_and_duplicate_409 PASSED         [ 13%]
tests/test_catalog.py::test_patch_product PASSED                         [ 20%]
tests/test_catalog.py::test_archive_restore_and_permanent_delete PASSED  [ 26%]
tests/test_catalog.py::test_bulk_mutations PASSED                        [ 33%]
tests/test_catalog.py::test_concurrent_edit_conflict_409 PASSED          [ 40%]
tests/test_catalog.py::test_upload_preview_and_commit_both_modes PASSED  [ 46%]
tests/test_catalog.py::test_upload_bad_rows_reported_with_row_numbers PASSED [ 53%]
tests/test_catalog.py::test_undo_and_snapshots PASSED                    [ 60%]
tests/test_catalog.py::test_pagination_and_query_filters PASSED          [ 66%]
tests/test_catalog.py::test_auth_public_key_403_and_tenant_isolation PASSED [ 73%]
tests/test_catalog.py::test_template_download PASSED                     [ 80%]
tests/test_catalog.py::test_full_catalogue_lifecycle_mocked_s3 PASSED    [ 86%]
tests/test_catalog.py::test_snapshot_pruning_to_10 PASSED                [ 93%]
tests/test_catalog.py::test_audit_log_contains_no_secrets PASSED         [100%]

============================= 15 passed in 33.38s =============================
```

### B. Full Test Suite Regression (`pytest tests/ -q`)
Executed across the entire project repository:
```
388 passed in 1442.86s (0:24:02)
Passed: 388 | Failed: 0 | Skipped: 0 | Errors: 0
```
Zero test regressions across all existing recommendation, accounts, onboarding, shopify, and tracking subsystems.

---

## 6. Live Verification Results

Live verification executed via `scripts/live_check_c1.py` against a running `uvicorn` instance (`http://127.0.0.1:8000`) using a throwaway test account:

```
======================================================================
STARTING C1 LIVE VERIFICATION
======================================================================

[1] Starting uvicorn on port 8000...
Backend server is UP and responding at http://127.0.0.1:8000

[2] Registering account: 'E2E Test C1 9e1355b8' (e2e_c1_9e1355b8@example.com)...
POST /v1/accounts/signup -> HTTP 201
Created Account ID: acc_awpv3h, Tenant ID: e2e_test_c1_9e1355b8

[3] Reading verification code via /v1/accounts/dev/last-verification...
GET /v1/accounts/dev/last-verification -> HTTP 200
Verification code received: 126190

[4] Verifying email address...
POST /v1/accounts/verify-email -> HTTP 200

[5] Logging in for session JWT...
POST /v1/accounts/login -> HTTP 200
JWT session established successfully.

[6] Seeding data/processed/e2e_test_c1_9e1355b8/products.csv via storage backend...
Successfully wrote 4 sample products to 'data/processed/e2e_test_c1_9e1355b8/products.csv'

[7] Calling GET /v1/catalog/summary to trigger auto-seeding...
GET /v1/catalog/summary -> HTTP 200
Summary response: {'active': 4, 'archived': 0, 'out_of_stock': 0, 'by_category': {'Accessories': 1, 'Keyboards': 1, 'Monitors': 1, 'Furniture': 1}, 'products_added_since_last_training': 4}
Verified: 'data/catalog/e2e_test_c1_9e1355b8/catalog.csv' auto-created and seeded with 4 active items.

[8] Exercising CRUD Lifecycle...
POST /v1/catalog/products -> HTTP 201 (Product: LIVE-P5)
PATCH /v1/catalog/products/LIVE-P5 -> HTTP 200 (New Price: 69.99)
DELETE /v1/catalog/products/LIVE-P5 -> HTTP 200 (Status: archived)
POST /v1/catalog/products/LIVE-P5/restore -> HTTP 200 (Status: active)

[9] Exercising Template & Multipart Upload Preview/Commit...
GET /v1/catalog/template?format=csv -> HTTP 200
POST /v1/catalog/upload (preview) -> HTTP 200
Preview diff: to_add=1, to_update=1, errors=[]
POST /v1/catalog/upload/0dc4ee5de03e333cba1bb89025711339/commit -> HTTP 200
Commit response: {'status': 'committed', 'upload_id': '0dc4ee5de03e333cba1bb89025711339', 'mode': 'upsert', 'applied': 2, 'added': 1, 'updated': 1, 'archived': 0}

[10] Exercising Audit History and Snapshot Undo...
GET /v1/catalog/history -> HTTP 200
Retrieved 6 audit changes. Most recent action: 'upload_commit' by 'account:acc_awpv3h'
POST /v1/catalog/undo -> HTTP 200
Undo response: {'status': 'restored', 'snapshot': 'snapshot-1795167543874-0dc4ee5de03e333cba1bb89025711339.csv', 'message': 'Catalogue successfully restored from pre-commit snapshot.', 'total_products': 5}
Summary after undo: active=5, archived=0

======================================================================
ALL LIVE VERIFICATION CHECKS PASSED SUCCESSFULLY!
======================================================================

>>> THROWAWAY TEST TENANT ID: e2e_test_c1_9e1355b8 <<<
>>> Company Name: E2E Test C1 9e1355b8
>>> Account ID: acc_awpv3h
======================================================================
```

---

## 7. Known Limitations (Pre-C2)

1. **Model Recommendations Integration (Resolved in Step C2):**
   - In Step C1, products added or updated in `data/catalog/{tenant_id}/catalog.csv` were visible in catalog API queries and summary metrics, but did not immediately reflect in recommendations without retraining.
   - *Status:* **Resolved in Step C2** (see [08_catalog_engine.md](file:///d:/Projects/AI_POD/docs/changes/08_catalog_engine.md)). Step C2 introduces `get_active_catalog` with 15-second TTL version-marker caching, candidates over-fetching, active set filtering, catalogue metadata enrichment, and out-of-stock filtering. Metadata edits (names, prices, images) now appear instantly in recommendations without model retraining.
2. **Retrain Pipeline Obeying Sovereign Catalogue (Resolved in Step C2):**
   - In Step C1, `src/pipeline/run.py` derived `data/processed/{tenant}/products.csv` directly from raw ingestion inputs.
   - *Status:* **Resolved in Step C2** (see [08_catalog_engine.md](file:///d:/Projects/AI_POD/docs/changes/08_catalog_engine.md)). In Step C2, `src/pipeline/run.py` treats `data/catalog/{tenant_id}/catalog.csv` as authoritative: candidates/negatives are strictly active catalogue products, interaction products missing from catalogue are safely added with optimistic concurrency, catalogue files are never overwritten, and `data/processed/{tenant}/products.csv` is built directly from active catalogue rows.
3. **Optimistic Concurrency Resolution:**
   - Clients updating catalog products must supply `If-Match` or `X-Catalog-Version` headers if they wish to guarantee concurrency control. If omitted, writes will succeed against the current state.

---

## 8. Manual Verification Script

To manually exercise the catalog API using PowerShell and `curl.exe`:

```powershell
# 1. Obtain JWT session token or private API key
$TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." # Replace with valid session token
$HEADERS = @{"Authorization" = "Bearer $TOKEN"}

# 2. Get catalogue summary
curl.exe -X GET "http://localhost:8000/v1/catalog/summary" -H "Authorization: Bearer $TOKEN"

# 3. Add a new product
curl.exe -X POST "http://localhost:8000/v1/catalog/products" `
  -H "Authorization: Bearer $TOKEN" `
  -H "Content-Type: application/json" `
  -d '{"product_id": "TEST-01", "product_name": "Test Gadget", "category": "Electronics", "price": 49.99}'

# 4. View paginated products
curl.exe -X GET "http://localhost:8000/v1/catalog/products?page=1&page_size=20" -H "Authorization: Bearer $TOKEN"

# 5. Archive product
curl.exe -X DELETE "http://localhost:8000/v1/catalog/products/TEST-01" -H "Authorization: Bearer $TOKEN"

# 6. View audit change history
curl.exe -X GET "http://localhost:8000/v1/catalog/history" -H "Authorization: Bearer $TOKEN"
```
