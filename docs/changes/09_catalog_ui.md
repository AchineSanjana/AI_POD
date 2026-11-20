# 09. Tenant-Managed Product Catalogue UI (Dashboard)

This document details the frontend implementation, backend integration, and verification for the tenant-managed product catalogue dashboard in AI_POD, accessible at `/dashboard/catalog`.

---

## 1. Files Created and Modified

### Frontend Files
- **`frontend/src/pages/dashboard/Catalog.jsx`** *(New)*: Complete catalogue management interface containing:
  - Metric summary cards (Active, Archived, Out of stock, Categories count)
  - Training status banner with dynamic states (`never_trained` vs pending additions/modifications vs up to date) and retrain button
  - Server-paginated product table with 300 ms debounced search, category filter, and status pills
  - Slide-over Add/Edit product drawer with client-side validation and inline error display
  - Permanent delete modal with explicit product ID confirmation input (strictly available for already-archived products)
  - 4-step Upload Wizard (template download, drag-and-drop file upload, mode selection, validation preview with row-level error table, atomic commit)
  - Change history drawer with actor, action, timestamp, item count, and "Undo last bulk change" modal
  - Safe Undo confirm modal detailing that undo restores the state prior to the last upload commit, reverts single-product edits made after that upload, shows the timestamp of that commit, and renders friendly error messages if no snapshot exists
  - Optimistic concurrency conflict banner (HTTP 409 handling with manual reload)
  - Toast feedback notification system
- **`frontend/src/api/client.js`** *(Modified)*:
  - Added module-level version store (`getLatestCatalogVersion`, `setLatestCatalogVersion`, `getCatalogMutationHeaders`).
  - Updated `request()` wrapper:
    - Automatically captures `ETag` and `X-Catalog-Version` response headers into the version store.
    - Omits setting `Content-Type: application/json` when payload is `FormData` (enabling browser multi-part boundaries).
    - Added support for `responseType: 'blob'` and `responseType: 'text'` (used for template downloads).
    - Formats HTTP 409 responses into structured `{ status: 409, code: 'conflict', message }` errors.
  - Implemented all 13 client API functions:
    - `getCatalogProducts(params)`
    - `getCatalogSummary()`
    - `addCatalogProduct(data)`
    - `patchCatalogProduct(productId, data)`
    - `archiveCatalogProduct(productId)`
    - `permanentDeleteCatalogProduct(productId)`
    - `restoreCatalogProduct(productId)`
    - `bulkCatalogAction(action, productIds)`
    - `downloadCatalogTemplate(format)`
    - `previewCatalogUpload(file, mode)`
    - `commitCatalogUpload(uploadId)`
    - `getCatalogHistory(limit)`
    - `undoCatalogCommit()`
- **`frontend/src/pages/dashboard/DashboardLayout.jsx`** *(Modified)*:
  - Added `Package` icon import from `lucide-react`.
  - Added navigation item `{ to: '/dashboard/catalog', icon: Package, label: 'Catalogue' }` to sidebar.
- **`frontend/src/App.jsx`** *(Modified)*:
  - Imported `Catalog` page component.
  - Registered route `<Route path="catalog" element={<Catalog />} />` under dashboard routes.

### Backend Files
- **`src/api/catalog.py`** *(Modified)*:
  - Updated `GET /v1/catalog/summary` to accept `response: Response` and populate `ETag` and `X-Catalog-Version` response headers with the current catalogue version marker.
  - Updated `POST /v1/catalog/undo` to accept `response: Response` and populate `ETag` and `X-Catalog-Version` with the newly restored catalogue version marker.
  - Configured `get_summary` and `undo_last_upload_commit` to resolve storage backend through `src.catalog.service.get_storage_backend()` ensuring dynamic test-harness monkeypatching is preserved.
- **`src/api/app.py`** *(Modified)*:
  - Configured `CORSMiddleware` with `allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`.
  - Configured `allow_headers` to include `*` plus explicit allowed request headers: `"Authorization"`, `"Content-Type"`, `"X-API-Key"`, `"X-Session-Token"`, `"X-AIPOD-Source"`, `"If-Match"`, `"X-Catalog-Version"`, and lowercase variants.
  - Configured `expose_headers` to include `*`, `"ETag"`, and `"X-Catalog-Version"`.

---

## 2. API Endpoints, Request/Response Shapes, and Storage Layout

### Authentication & Keys
All catalogue endpoints require admin credentials verified by `get_tenant_for_admin_action`:
- **Private Admin API Keys**: Prefixed with `sk-` (e.g. `sk-<tenant>-xxxx`). Authenticated via `X-API-Key` header.
- **Bearer JWT Tokens**: Authenticated via `Authorization: Bearer <jwt>` containing tenant and user claims.
- **Public API Keys**: Prefixed with `pk-` (e.g. `pk-<tenant>-xxxx`). Requests with `pk-` keys are rejected by the public key enforcement middleware with **HTTP 403 Forbidden**.
- **Tenant Isolation**: Tenant identity is strictly derived from the verified credentials; request bodies and query parameters cannot specify or override the tenant.

### Audit Log & Actor Resolution
When catalogue mutations are saved, `_resolve_actor` extracts the actor identity:
- If a Bearer JWT contains `sub` or `account_id`: `account:{account_id}`
- If a Bearer JWT lacks account ID: `tenant:{tenant_id}:session`
- If an `sk-` private API key is used: `tenant:{tenant_id}:private_key`
- Fallback: `tenant:{tenant_id}:admin`

Audit log entries are stored as isolated daily part files:
`data/catalog/{tenant_id}/audit/{YYYY-MM-DD}/part-{timestamp_ms}-{pid}-{random_hex}.jsonl`

### Storage Layout for Pending Uploads and Snapshots
- **Pending Uploads**:
  - Previews are stored in the storage backend at:
    `data/catalog/{tenant_id}/pending/{upload_id}.json`
  - Each pending upload JSON contains metadata, rows to apply, and an expiration timestamp set to 1 hour (3600 seconds) after creation.
- **Snapshots**:
  - Taken immediately prior to applying a commit or replacement:
    `data/catalog/{tenant_id}/snapshots/snapshot-{timestamp_ms}-{upload_id}.csv`
  - Pruned automatically to keep at most the **last 10 snapshots** (`MAX_SNAPSHOTS = 10`).

### Optimistic Concurrency Protocol
- **Read endpoints** (`GET /v1/catalog/products`, `GET /v1/catalog/summary`):
  - Return headers: `ETag: "<version_marker>"` and `X-Catalog-Version: <version_marker>`.
  - The client captures this marker into module-level state.
- **Mutating endpoints** (`POST /v1/catalog/products`, `PATCH /v1/catalog/products/{id}`, `DELETE /v1/catalog/products/{id}`, `POST /v1/catalog/products/{id}/restore`, `POST /v1/catalog/bulk`, `POST /v1/catalog/upload/{id}/commit`, `POST /v1/catalog/undo`):
  - The client sends: `If-Match: "<version_marker>"` and `X-Catalog-Version: <version_marker>`.
  - If the marker in storage changed since the read, atomic writing fails and returns `409 Conflict`.
  - The frontend maps 409 responses to `{ status: 409, code: "conflict" }`, displaying the conflict banner prompting a manual reload.

---

## 3. Real Endpoint Contracts (from `src/api/catalog.py` & `src/api/schemas.py`)

#### 1. `GET /v1/catalog/products`
- **Query Params**: `query` (str), `category` (str), `status` (`active` | `archived` | `all`, default `active`), `page` (int, ge 1), `page_size` (int, ge 1, le 100).
- **Headers Exposed**: `ETag: "<version>"`, `X-Catalog-Version: <version>`.
- **Response**: `CatalogProductsResponse`:
  ```json
  {
    "items": [
      {
        "product_id": "P101",
        "product_name": "Ergonomic Keyboard",
        "category": "Office",
        "status": "active",
        "brand": "KeyPro",
        "price": 89.99,
        "in_stock": 1,
        "description": "Split wireless keyboard",
        "image_url": "https://example.com/p101.jpg",
        "product_url": "https://example.com/p101",
        "created_at": "2026-11-20T10:00:00Z",
        "updated_at": "2026-11-20T10:00:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 25,
    "total_pages": 1
  }
  ```

#### 2. `GET /v1/catalog/summary`
- **Headers Exposed**: `ETag: "<version>"`, `X-Catalog-Version: <version>`.
- **Response**: `CatalogSummaryResponse`:
  ```json
  {
    "total": 12,
    "active": 10,
    "archived": 2,
    "out_of_stock": 1,
    "by_category": { "Office": 5, "Electronics": 5 },
    "products_added_since_last_training": 2,
    "products_changed_since_last_training": 1,
    "last_training_at": "2026-11-19T12:00:00Z",
    "never_trained": false
  }
  ```

#### 3. `POST /v1/catalog/products`
- **Headers Sent**: `If-Match: "<version>"`, `X-Catalog-Version: <version>`.
- **Request Body**: `ProductCreateRequest` (`product_id` required, `product_name` required, `category` required, `brand`, `price` >= 0, `in_stock`, `description`, `image_url`, `product_url`).
- **Response Status**: `201 Created` (returns product dict).
- **Errors**: `409 Conflict` on duplicate ID or version mismatch.

#### 4. `PATCH /v1/catalog/products/{product_id}`
- **Headers Sent**: `If-Match: "<version>"`, `X-Catalog-Version: <version>`.
- **Request Body**: `ProductUpdateRequest` (partial fields).
- **Response Status**: `200 OK` (returns updated product dict).

#### 5. `DELETE /v1/catalog/products/{product_id}`
- **Headers Sent**: `If-Match: "<version>"`, `X-Catalog-Version: <version>`.
- **Query Param**: `permanent=true` (optional boolean, default `false`).
- **Rules**:
  - `permanent=false`: Archives product (soft delete). Returns `200 OK` (`{"message": "Product archived", "status": "archived", "product_id": "..."}`).
  - `permanent=true`: Only permitted if product is ALREADY archived. If active, returns `400 Bad Request` (`{"detail": "Only already-archived products can be permanently deleted. Archive the product first."}`). Returns `200 OK` (`{"message": "Product permanently deleted", "status": "deleted", "product_id": "..."}`).

#### 6. `POST /v1/catalog/products/{product_id}/restore`
- **Headers Sent**: `If-Match: "<version>"`, `X-Catalog-Version: <version>`.
- **Response Status**: `200 OK` (`{"message": "Product restored", "status": "active", "product_id": "..."}`).

#### 7. `POST /v1/catalog/bulk`
- **Headers Sent**: `If-Match: "<version>"`, `X-Catalog-Version: <version>`.
- **Request Body**: `BulkCatalogActionRequest`:
  ```json
  { "action": "archive", "product_ids": ["P101", "P102"] }
  ```
  *(Supported actions: `archive`, `restore`, `delete`. Limit: max 500 product IDs).*
- **Response**: `BulkCatalogActionResponse`:
  ```json
  { "action": "archive", "affected": 2, "product_ids": ["P101", "P102"] }
  ```

#### 8. `GET /v1/catalog/template?format=csv`
- **Response**: CSV stream with headers (`product_id,product_name,category,status,brand,price,in_stock,description,image_url,product_url`) and one example row. `Content-Type: text/csv`.

#### 9. `POST /v1/catalog/upload`
- **Form Data**: `file` (multipart CSV, JSON, XLSX <= 20 MB, <= 100k rows), `mode` (`upsert` | `replace`, default `upsert`).
- **Behavior**: Preview-only. Stores pending JSON in `data/catalog/{tenant_id}/pending/{upload_id}.json`.
- **Response**: `UploadPreviewResponse`:
  ```json
  {
    "upload_id": "upl_a1b2c3d4e5f6",
    "mode": "upsert",
    "total_rows": 25,
    "to_add": 5,
    "to_update": 20,
    "to_archive": 0,
    "errors": [],
    "expires_at": "2026-11-20T20:30:00Z"
  }
  ```

#### 10. `POST /v1/catalog/upload/{upload_id}/commit`
- **Headers Sent**: `If-Match: "<version>"`, `X-Catalog-Version: <version>`.
- **Behavior**: Takes snapshot `data/catalog/{tenant_id}/snapshots/snapshot-{ts}-{upload_id}.csv`, prunes snapshots to 10, writes changes atomically, logs audit entry, deletes pending file.
- **Response**: `UploadCommitResponse`:
  ```json
  {
    "status": "committed",
    "upload_id": "upl_a1b2c3d4e5f6",
    "mode": "upsert",
    "added": 5,
    "updated": 20,
    "archived": 0,
    "total_active": 25,
    "snapshot": "snapshot-1732115400000-upl_a1b2c3d4e5f6.csv"
  }
  ```

#### 11. `GET /v1/catalog/history?limit=50`
- **Response**: `CatalogHistoryResponse`:
  ```json
  {
    "tenant_id": "tenant_cat_a",
    "changes": [
      {
        "tenant_id": "tenant_cat_a",
        "who": "tenant:tenant_cat_a:private_key",
        "when": "2026-11-20T19:30:00Z",
        "action": "upload_commit",
        "product_ids_count": 25,
        "product_ids": ["P101", "P102"],
        "details": { "mode": "upsert", "added": 5, "updated": 20 }
      }
    ]
  }
  ```

#### 12. `POST /v1/catalog/undo`
- **Headers Sent**: `If-Match: "<version>"`, `X-Catalog-Version: <version>`.
- **Behavior**: Restores the latest snapshot from `data/catalog/{tenant_id}/snapshots/`, deletes that snapshot, writes an `undo` audit entry, and sets `ETag` + `X-Catalog-Version` on the response.
- **Response**: `CatalogUndoResponse`:
  ```json
  {
    "status": "restored",
    "snapshot": "snapshot-1732115400000-upl_a1b2c3d4e5f6.csv",
    "message": "Catalogue successfully restored from pre-commit snapshot.",
    "total_products": 20
  }
  ```
- **Error When No Snapshot Exists**:
  Returns HTTP `400 Bad Request` with:
  ```json
  { "detail": "No snapshot available to undo." }
  ```
  *(The UI displays this error directly inside the Undo modal rather than crashing).*

---

## 4. Verification Methodology: Verified by Running vs Verified Only by Build/Lint

### Verified by Running (Automated Tool Executions)
The following were verified by executing pytest and CLI tools in the workspace:
1. **CORS Preflight & Expose Headers**:
   - Sent real OPTIONS preflight requests with `Origin: http://localhost:5173` requesting `Authorization`, `Content-Type`, `X-API-Key`, `X-Session-Token`, `X-AIPOD-Source`, `If-Match`, `X-Catalog-Version` against `/v1/catalog/products` and `/v1/recommendations`. Verified 200 OK and allowed headers.
   - Sent GET requests to `/v1/catalog/products` and `/v1/catalog/summary` with `Origin: http://localhost:5173`. Verified `Access-Control-Expose-Headers` contains `ETag` and `X-Catalog-Version`.
2. **Undo Safety Gate**:
   - Calling `POST /v1/catalog/undo` when no snapshots exist verified to return HTTP 400 with `"detail": "No snapshot available to undo."` without an unhandled server error.
3. **Backend Optimistic Concurrency & Data Operations**:
   - Seeding from `products.csv` on first access.
   - 409 Conflict on duplicate `product_id` and outdated version markers.
   - Soft delete (archive) and permanent delete restrictions (active products return 400).
   - Multipart file upload preview (CSV, JSON, XLSX), row error reporting, and commit in both `upsert` and `replace` modes.
   - Snapshot creation, retention pruning (max 10), and undo rollback.
   - S3 StorageBackend lifecycle integration via moto.
   - Active catalog cache, in-memory TTL coherency, and recommendation filtering.
4. **Code Quality & Production Build**:
   - `oxlint` executed across all 29 frontend files: **0 errors**.
   - `vite build` executed: compiled production bundles cleanly in 2.75s.

### Verified Only by Build/Lint, NOT in a Live Browser Session
The following user interaction states are verified by component code structure, prop contracts, and static build/lint, but **have not been clicked through manually in a running web browser**:
1. Exact visual placement of the sidebar "Catalogue" icon and navigation active-state highlight.
2. User mouse drag-and-drop interaction in the upload file zone.
3. Opening the slide-over Add/Edit drawer, typing into input fields, and saving via mouse click.
4. Typing the exact product ID into the permanent delete dialog input in a real browser window.
5. Live multi-tab concurrent modification race conditions clicked simultaneously in two side-by-side browser tabs.

---

## 5. Manual Browser Test Script

Use this protocol to verify the catalogue UI end-to-end in a running browser (`http://localhost:5173`) with backend running (`http://localhost:8000`).

### Step a: Navigation and Initial Load
1. Log in to the application and navigate to `/dashboard`.
2. Confirm the left sidebar contains **"Catalogue"** with a Package icon between "Overview" and "Model Status".
3. Click **"Catalogue"**. Verify route changes to `/dashboard/catalog`.
4. Verify skeleton loading placeholders appear briefly before data renders.
5. Confirm no mock data is shown; counts and products reflect the real tenant catalogue.

### Step b: Summary Cards & Training Banner Lifecycle
1. Inspect the 4 summary cards: Active Products, Archived Products, Out of Stock, Categories.
2. **Verify Training Banner Lifecycle**:
   - **Initial State**: If the model was previously trained and no products were added, the banner is hidden.
   - **Add Product Trigger**: Add a new product via the UI (e.g. `PROD-NEW-01`).
   - Observe that the training banner appears: `"1 new and 0 changed products since last training. New products appear in the catalogue and similar results immediately, but in personalised recommendations only after retraining."`
   - Click the **"Retrain Model"** button on the banner. Confirm a training run is initiated via `POST /v1/onboard/train` and the app navigates to `/onboarding/training`.
   - After retraining completes, return to `/dashboard/catalog`. Verify the banner is gone (`products_added_since_last_training: 0`).

### Step c: Table Filtering, Search, and Pagination
1. **Search**: Enter text in "Search products...". Confirm search is debounced by 300 ms and filters across ID, name, brand, and description. Click X to clear.
2. **Category Filter**: Select a category from the dropdown (options sourced from `summary.by_category`). Confirm list filters by category.
3. **Status Filter**: Click "Active" (default), "Archived" (dimmed rows with Archived badge), and "All".
4. **Pagination**: Switch page size (25, 50, 100) and click Next/Prev buttons.

### Step d: Add Product & Public Key Security Check
1. **Add Product**:
   - Click **"+ Add Product"**. Test client validation (empty fields show "Required", negative price shows error).
   - Enter valid details: ID `item-prod-10`, Name `Wireless Ergonomic Mouse`, Category `Accessories`, Price `49.99`, In Stock `ON`.
   - Click "Add Product". Confirm toast notification and product appears in the table.
2. **Public Key Security Gate (`pk-` check)**:
   - In terminal or API client, send `GET /v1/catalog/products` using a public key (`X-API-Key: pk-<tenant>-xxxx`).
   - Confirm the API returns **HTTP 403 Forbidden** (`{"detail": "Public API keys are restricted to recommendation and tracking endpoints."}`).

### Step e: Edit Product
1. Click the row for `item-prod-10`. Slide-over drawer opens titled "Edit Product: item-prod-10".
2. Confirm Product ID is disabled and read-only.
3. Change price to `39.99` and toggle "In Stock" to OFF.
4. Click "Save Changes". Confirm row updates to `$39.99` with amber "Out of stock" badge.

### Step f: Archive Single Product & Recommendation Exclusion Check
1. In the row for `item-prod-10`, click the **"Archive"** button.
2. Confirm the product disappears from the "Active" filter view.
3. **Verify Recommendation Exclusion**:
   - Send `GET /v1/recommendations?customer_id=cust_test&top_n=10` with header `X-AIPOD-Source: wizard-test` and `X-API-Key: sk-<tenant>-xxxx`.
   - Inspect the returned product recommendations. Confirm `item-prod-10` is NOT present in the recommendations list.
4. Switch catalogue status filter to "Archived", locate `item-prod-10`, and click **"Restore"**. Verify it returns to active status and becomes eligible for recommendations.

### Step g: Bulk Archive and Restore
1. In table header, check "Select all on page".
2. Confirm sticky bottom action bar appears showing "N products selected".
3. Click "Archive Selected". Confirm confirmation modal opens.
4. Click "Yes, archive". Verify all selected items are archived via `POST /v1/catalog/bulk` and selection clears.
5. Switch to "Archived" view, select items, and click "Restore Selected" to restore them.

### Step h: Permanent Delete (Safety Gate)
1. Ensure a test product (e.g. `item-prod-10`) is archived.
2. Click the archived row to open the edit drawer.
3. Scroll to the bottom; verify the red danger button **"Permanently Delete Product"** is visible (strictly absent for active products).
4. Click "Permanently Delete Product". Danger modal opens warning that this action is irreversible.
5. Confirm "Delete Permanently" button is disabled until you type `item-prod-10` exactly.
6. Type `item-prod-10` and click "Delete Permanently". Product is deleted via `DELETE /v1/catalog/products/item-prod-10?permanent=true`.

### Step i: Upload Wizard (4 Steps)
1. Click **"Upload Catalogue"** at top.
2. **Step 1 (Template)**: Click "Download CSV Template". Confirm `catalog_template.csv` downloads.
3. **Step 2 (Select)**: Drag and drop a CSV file. Select mode: "Add and update (safe)" or "Replace catalogue" (warning shows that missing products will be archived).
4. **Step 3 (Preview)**: Click "Analyze & Preview". Verify `to_add`, `to_update`, `to_archive` pills appear. If errors exist, scrollable row error table shows and commit button is disabled. If valid, commit button is enabled and shows "Preview expires in 1 hour".
5. **Step 4 (Commit)**: Click "Commit & Apply Changes". Verify success screen displays applied counts and table reloads.

### Step j: History & Undo Safety
1. Click **"History"** in top toolbar. History drawer opens showing audit entries with formatted timestamps, action badges, actor identity (`who`), and affected counts.
2. Click **"Undo Last Bulk Change"**.
3. **Verify Undo Safety Modal**:
   - Confirm modal states: *"Undo restores the catalogue as it was before the LAST UPLOAD COMMIT. Any single-product edits made after that upload will also be reverted."*
   - Confirm modal displays: *"Time of last upload commit: [formatted date/time]"* (or friendly fallback if no commit found).
   - If no snapshot exists in storage, confirm clicking "Restore Snapshot" renders a friendly error message inside the modal: *"No snapshot available to undo. You can only undo after committing a catalogue upload."* without crashing.
   - If snapshot exists, click "Restore Snapshot". Verify catalogue rolls back to pre-commit snapshot, drawer closes, and table and summary refresh with the restored version marker.

---

## 6. Automated Verification Results (Real Command Outputs)

### 1. Pytest Backend Verification (`tests/test_catalog.py`, `tests/test_catalog_engine.py`, `tests/test_api_v1.py`)
```
PS D:\Projects\AI_POD> .\venv\Scripts\pytest tests/test_catalog.py -q
..................                                                       [100%]
18 passed in 41.43s

PS D:\Projects\AI_POD> .\venv\Scripts\pytest tests/test_catalog_engine.py -q
............                                                             [100%]
12 passed in 22.83s

PS D:\Projects\AI_POD> .\venv\Scripts\pytest tests/test_api_v1.py -q
..........                                                               [100%]
10 passed in 28.24s
```
**Total: 40 tests passed, 0 failed.**

### 2. Frontend Lint Verification (`npm run lint` via `oxlint`)
```
PS D:\Projects\AI_POD\frontend> npm run lint

> frontend@0.0.0 lint
> oxlint

Found 15 warnings and 0 errors.
Finished in 167ms on 29 files with 104 rules using 8 threads.
```

### 3. Frontend Production Build (`npm run build` via `vite build`)
```
PS D:\Projects\AI_POD\frontend> npm run build

> frontend@0.0.0 build
> vite build

vite v8.3.5 building client environment for production...
transforming...
✓ 2637 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.93 kB │ gzip:   0.49 kB
dist/assets/index-DzKvr4YD.css    8.36 kB │ gzip:   2.65 kB
dist/assets/index-KlN0st_x.js   855.16 kB │ gzip: 240.10 kB

[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 2.75s
```
