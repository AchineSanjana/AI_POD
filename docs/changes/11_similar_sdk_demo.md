# Step S2: Storefront Similar Products & SDK Integration

## 1. Executive Summary

Step S2 brings algorithmic Similar Products directly into storefronts through an enhanced zero-dependency JavaScript SDK (`static/sdk.js`), responsive client components (mobile scroll-snap carousel and side-by-side comparison table), full-funnel interaction and click telemetry tracking, and an authentic Mobitel LifeStore  electronics demo portal (`demo/similar_products.html`).

All backend changes are strictly **additive** and preserve 100% backward compatibility:
- The four core recommendation tournament models, training pipeline, and `final_model.joblib` remain untouched.
- Multi-worker cache coherency and `STORAGE_BACKEND=s3` remain fully supported.
- Multi-tenant credential scopes (`pk-...` public key vs `sk-...` secret key) are strictly enforced.

---

## 2. Tenant Coherence Report

### Investigation of Prior S2 Artifacts
- **Previous Screenshot URL:** `http://localhost:5500/similar_products.html?base=http://127.0.0.1:8000&key=pk-telco-xxxx&product=SP-01`
- **Tenant Key:** `pk-telco-xxxx` belongs to non-throwaway tenant `telco_default`.
- **Product ID:** `SP-01` originated from the synthetic catalogue generator created for throwaway tenant `e2e_test_s2_*`.

### Inspection of `data/catalog/`
Inspection of local storage confirmed the existence of a catalogue file in the non-throwaway tenant:
- **File:** `data/catalog/telco_default/catalog.csv`
- **Size:** 8,082 bytes
- **Rows:** 30 product rows (Header + 10 Smartphones `SP-01`..`SP-10`, 10 Laptops `LP-01`..`LP-10`, 10 Audio Accessories `AD-01`..`AD-10`)
- **Created Timestamp:** `2026-11-22T19:58:31 UTC`
- **Action Taken:** Per explicit instructions ("DO NOT delete or modify them; report to me"), this file was left **completely untouched and unmodified**.
- **Going-Forward Policy:** All browser verifications, automated tests, and demo runs strictly generate and use fresh throwaway tenants (`e2e_tenant_*`) with their own `pk-` keys and catalogue datasets.

---

## 3. Architecture & Code Changes

### A. Dynamic Target Product Rendering (No Static Fakes)
In `demo/similar_products.html`:
1. **Dynamic Target Card:** All target product attributes (`product_name`, `price`, `brand`, `category`, `specs`, `image_url`, and `in_stock` badge) render dynamically from the API response `target` object via `updateTargetCard()`.
2. **Neutral Skeleton State:** Before API response arrives, the page displays neutral shimmer skeleton elements (`.skeleton-shimmer`) for image, brand, title, category, price, and spec grid.
3. **Error Handling State:** On API network failure or non-200 error, `showTargetError()` renders an explicit error container (`#target-card-error`) displaying the failure message, rather than showing static fake data.
4. **Clean Switcher Pills:** The device switcher tabs contain product IDs only (`SP-01`, `SP-02`, `SP-03`, `SP-04`) without hardcoded device names, prices, or specifications.

### B. CTR Formula, Multi-Click De-duplication & Clamping
In `src/telemetry/reader.py`:
- **Mathematical Formula:**
  $$\text{similar\_ctr} = \frac{|\{\text{distinct } \text{rec\_id} \text{ with } \ge 1 \text{ click in period}\}|}{\text{non-test similar requests in period}}$$
  $$\text{recommendation\_ctr} = \frac{|\{\text{distinct } \text{rec\_id} \text{ with } \ge 1 \text{ click in period}\}|}{\text{non-test recommendation requests in period}}$$
  Expressed in Python:
  ```python
  similar_ctr = (
      round(min(1.0, len(similar_clicked_rec_ids) / similar_requests), 4)
      if similar_requests > 0
      else None
  )
  ```
- **Why Clamping is Required:**
  1. **Asynchronous Lifecycle:** Page view requests and user clicks occur across decoupled user interactions. Clicks can be reported in the current analytics period for requests issued just before the period boundary.
  2. **Bounded Metric:** CTR is a ratio bounded between $0.0$ and $1.0$. Applying `min(1.0, ...)` guarantees that out-of-window requests or dropped request packets never produce an invalid CTR $> 1.0$.
  3. **Multi-Click De-duplication:** `similar_clicked_rec_ids` is stored as `set[str]`. Multiple clicks (e.g. 3 clicks) on the same recommendation `rec_id` increment `similar_clicks` to 3, but contribute exactly 1 distinct `rec_id` to `similar_ctr`.
  4. **Traffic Isolation:** Requests and clicks with `X-AIPOD-Source: wizard-test` are strictly excluded from both the numerator and denominator.

### C. Standard-Compliant CORS Configuration
In `src/api/app.py`:
- **Credentials Policy:** `allow_credentials=False`. FastAPI's `CORSMiddleware` strictly forbids `allow_origins=["*"]` when `allow_credentials=True`.
- **Allowed Origins:** Configured via `CORS_ORIGINS` environment variable (comma-separated). When omitted, defaults to:
  ```python
  allowed_origins = [
      "http://localhost:5173",
      "http://127.0.0.1:5173",
      "http://localhost:5500",
      "http://127.0.0.1:5500",
  ]
  ```
- **Allowed Headers:** `Authorization`, `Content-Type`, `X-API-Key`, `X-Session-Token`, `X-AIPOD-Source`, `If-Match`, `X-Catalog-Version` (case-insensitive).
- **Exposed Headers:** `ETag`, `X-Catalog-Version`.
- **Public SDK Delivery (`/sdk.js` and `/v1/sdk.js`):** Served with `Cache-Control: public, max-age=300` and `Access-Control-Allow-Origin: *` to enable public script loading from any client storefront origin.
- **Documentation:** `.env.example` updated with `CORS_ORIGINS` configuration example.

---

## 4. Cold Start Benchmarks & Single-Flight Concurrency

### Benchmarks (Reproduced via `tests/test_similar_storefront.py::test_cold_start_and_single_flight`)
- **5,000 Products Catalogue:**
  - Cold Start Index Build Time: **1.18 seconds** (well within `< 5.0s` target).
  - Single-Flight Concurrency: 4 concurrent worker threads requesting cold tenant index simultaneously trigger feature extraction exactly once. Three workers wait on `_TENANT_BUILD_LOCKS[tenant_id]` reentrant lock and immediately reuse the cached matrix.
- **50,000 Products Catalogue:**
  - Cold Start Index Build Time: **3.74 seconds** (`< 5.0s`).
  - Large Catalogue Guard: When catalog size exceeds `LARGE_CATALOG_THRESHOLD = 10_000`, the build lazily filters candidates by the requested product's category, bounding peak memory consumption.
- **Non-Blocking Threadpool:** The similarity endpoint is defined with synchronous `def` in FastAPI, allowing AnyIO threadpool workers to execute matrix calculations without blocking the main event loop.

---

## 5. Playwright + Chromium Real Browser Verification

Script: `scripts/verify_s2_browser.py`
Pytest Wrapper: `tests/test_s2_browser.py`

### Test Setup
- **Throwaway Tenant:** Generated dynamically via `POST /v1/accounts/signup` (`e2e_tenant_4ebe5b95`).
- **Catalogue:** 30 products (10 Smartphones, 10 Laptops, 10 Audio Accessories).
- **Security Check:** Product `SP-10` injected with XSS payload: `<img src=x onerror=alert(1)>`.
- **Server Ports:** API on `http://127.0.0.1:8000`, Demo on `http://127.0.0.1:5500`.

### Assertion Results Across Viewports

| # | Assertion Check | Mobile (390x844) | Mobile (360x800) | Desktop (1280x900) |
|---|---|:---:|:---:|:---:|
| **(a)** | Status pill says Connected | **PASS** | **PASS** | **PASS** |
| **(b)** | $\ge 3$ `.aipod-sim-card` elements visible | **PASS** (6 cards) | **PASS** (6 cards) | **PASS** (6 cards) |
| **(c)** | Compare table exists with $\ge 2$ product cols | **PASS** (6 headers) | **PASS** (6 headers) | **PASS** (6 headers) |
| **(d)** | `document.documentElement.scrollWidth <= window.innerWidth` (no page overflow) | **PASS** (390px $\le$ 390px) | **PASS** (360px $\le$ 360px) | **PASS** (1280px $\le$ 1280px) |
| **(e)** | Zero unhandled console errors | **PASS** (0 errors) | **PASS** (0 errors) | **PASS** (0 errors) |
| **(f)** | Card click sends `POST /v1/track` with `source="similar"` and hex `rec_id` | **PASS** (`rec_id: e3011ffd...`) | **PASS** (`rec_id: a23a4384...`) | **PASS** (`rec_id: 6fc4dadb...`) |
| **(g)** | Telemetry flush reflects `similar_clicks >= 1` in `GET /v1/dashboard/analytics` | **PASS** (clicks: 1) | **PASS** (clicks: 1) | **PASS** (clicks: 3) |
| **(h)** | XSS product name renders as text; zero dialogs/scripts executed | **PASS** (0 dialogs) | **PASS** (0 dialogs) | **PASS** (0 dialogs) |

### Overflow Prevention CSS Fixes
- `min-width: 0` applied to `.header-inner`, `.brand-wrap`, `.nav-actions`, `.target-card`, `.target-image-wrap`, and `.target-info`.
- Header inner wrapped with `flex-wrap: wrap`.
- Device switcher pills isolated in dedicated `overflow-x: auto` strip with `-webkit-overflow-scrolling: touch`.
- Carousel and comparison table are the only containers permitted horizontal scrolling (`.aipod-sim-grid` scroll-snap on mobile, `.aipod-sim-compare-wrap` table container).

### Full-Page Screenshots Captured
All screenshots captured using Playwright `full_page=True`:
1. `docs/screenshots/s2_mobile_full.png` (390x844 viewport, full page)
2. `docs/screenshots/s2_mobile.png` (390x844 viewport, full page, overwrote prior mobile image)
3. `docs/screenshots/s2_compare_mobile.png` (390x844 viewport, full page showing comparison matrix)
4. `docs/screenshots/s2_desktop_full.png` (1280x900 viewport, full page)

---

## 6. Verification Breakdown

### A. Verified in a Real Browser (Playwright + Chromium)
1. **SDK Dynamic Loading:** Dynamic script tag injection from `<base>/sdk.js` with attributes `data-tenant-key`, `data-api-base`, `data-currency`, and `data-locale`.
2. **Pill Connection States:** Transitions from neutral to `"Connected (pk-...)"` upon SDK initialization.
3. **Target Card Dynamic Rendering:** Shimmer skeleton placeholders display during load; populated with API response data upon arrival.
4. **Responsive Layouts & Overflow:** Viewports 390x844, 360x800, and 1280x900 verified via DOM evaluation: `document.documentElement.scrollWidth <= window.innerWidth`.
5. **Interactive Click Telemetry:** Card clicks intercepted at network layer; verified `POST /v1/track` payload containing `event_type="click"`, `source="similar"`, and 16-hex `rec_id`.
6. **Analytics Integration:** Flushed telemetry events queried via `GET /v1/dashboard/analytics` showing incremented `similar_clicks`.
7. **XSS Defense:** Malicious string `<img src=x onerror=alert(1)>` rendered safely as plain escaped text in target card; verified zero alert dialogs triggered.

### B. Verified by HTTP Calls or Static Checks
1. **CORS Options Preflight:** OPTIONS requests with `Origin: http://localhost:5500` return 200, matching origin, `allow_credentials=False`, and allow listed headers.
2. **Unauthorized Origin Rejection:** OPTIONS requests from `http://evil-unauthorized-site.com` return no `Access-Control-Allow-Origin`.
3. **Header Exposure:** Verified `ETag` and `X-Catalog-Version` present in `Access-Control-Expose-Headers`.
4. **422 Validation:** POST `/v1/track` rejects invalid `source` values and non-hex or $>32$-character `rec_id` with HTTP 422.
5. **CTR Math & Clamping:** Test `test_ctr_distinct_rec_ids_and_clamping` verified multi-click de-duplication (3 clicks on 1 rec_id = 1), `wizard-test` traffic exclusion, and strict ratio clamping $\le 1.0$.
6. **Cold Start Latency:** Benchmark verified $<5.0$s on 5,000 and 50,000 product catalogues.
7. **SDK File Size:** Static asset `static/sdk.js` measures 25,434 bytes, strictly under the 25,600 byte ceiling.

---

## 7. Modified Existing Tests Summary

| Test File | Reason for Modification |
|---|---|
| `tests/test_similar_storefront.py` | Added Step S2 test suite covering cold start benchmarks, CORS preflight, `rec_id` response schemas, `POST /v1/track` source/rec_id validation, and CTR distinct `rec_id` click de-duplication/clamping. |
| `tests/test_catalog.py` | Updated line 880 in `test_cors_preflight_catalogue_and_recommendations_routes` to assert `access-control-allow-credentials` is not true, matching the new standard `allow_credentials=False` CORS configuration. |
| `tests/test_api_auth.py` | Restored original strict assertion `rec_ids.issubset(telco_products)` against clean telco tenant with no catalogue; added `test_alias_keys_cannot_mutate_catalog_for_real_tenants`. |
| `tests/test_api_multitenancy.py` | Restored original strict assertion `telco_rec_pids == expected_direct_recs` and subset check against the 10 clean telco products. |
| `tests/test_pipeline_s3_e2e.py` | Removed S3 catalogue seeding workaround and restored direct `model_local.recommend(test_customer_id, top_k=5)`. |

---

## 8. Post-S2 Cleanup & Hardening Report

### A. Stray Catalogue Investigation & Source Identification
- **Root Cause:** In commit `f48165e`, a 30-product demo catalogue (`SP-01`..`SP-10`, `LP-01`..`LP-10`, `AD-01`..`AD-10` from `build_30_products()`) was committed into `data/catalog/telco_default/catalog.csv` during manual testing of `demo/similar_products.html` with default query parameters `key=pk-telco-xxxx&product=SP-01`.
- **Catalogue Removal & Model Retraining:** The stray catalogue directory `data/catalog/telco_default/` was removed by the user. Running `scripts/run_pipeline.py --tenant_id telco_default` retrained the tournament models cleanly against the original 10 Telco services (`InternetService_Fiber`, `DeviceProtection`, `OnlineSecurity`, `TechSupport`, `PhoneService`, `MultipleLines`, `OnlineBackup`, `StreamingTV`, `StreamingMovies`, `InternetService_DSL`). `LearnedRankingRecommender` was restored as the champion model.
- **Script Audit:** Verified all verification scripts (`scripts/verify_s2_browser.py`, `scripts/verify_s2_storefront.py`, `scripts/live_check_s1.py`, `scripts/live_check_c1.py`, `scripts/live_check_c2.py`). All scripts generate unique throwaway tenants (prefixed with `e2e_tenant_*` or `e2e_test_*`) and exclusively use their own isolated credentials and datasets.

### B. Reversion of Test Workarounds
All three test suites modified in commit `781d5e7` were restored to their original strict assertions:
1. `tests/test_api_auth.py`: Reverted `test_cross_tenant_spoofing_prevented_in_body_and_query` to assert `assert rec_ids.issubset(telco_products)` directly without active catalogue fallbacks.
2. `tests/test_api_multitenancy.py`: Reverted `test_api_multitenancy_telco_ecommerce_isolation` to assert `assert set(telco_rec_pids).issubset(telco_catalog_ids)` and `assert telco_rec_pids == expected_direct_recs`.
3. `tests/test_pipeline_s3_e2e.py`: Removed mocked S3 catalogue uploading code (`s3_client.put_object(...)` for `data/catalog/telco_default/catalog.csv`) and restored clean direct recommendation assertion `assert s3_recs == local_recs`.

### C. Implementation of System Guards
1. **Repository State Guard Fixture (`tests/conftest.py`):**
   - Implemented a session-scoped autouse pytest fixture (`guard_repository_state`) that snapshots file paths, sizes, and tenant records for `data/catalog/`, `data/telemetry/`, `config/config.yaml`, `config/accounts.local.yaml`, and `config/tenants_auth.local.yaml`.
   - At session teardown, fails the test session if any files or records belonging to real/production tenants (non-`e2e_*` / non-test tenants) were created, modified, or deleted, or if persistent configuration (`config.yaml`) was mutated.
2. **Catalogue Write Lockout for Demo Alias Keys (`src/api/auth.py`):**
   - Hardened `get_tenant_for_admin_action` and `get_current_tenant` to check `is_real_tenant(resolved_tenant)`.
   - When a demo alias key (`sk-*-xxxx` or `pk-*-xxxx`) attempts to invoke catalogue write endpoints (`POST`, `PATCH`, `DELETE` under `/v1/catalog/*` or `/catalog/*`) on any real tenant, the request is rejected with `HTTP 403 Forbidden`.
   - Catalogue read endpoints (`GET /v1/catalog/*`) continue to function for demo keys.
   - Added unit test `test_alias_keys_cannot_mutate_catalog_for_real_tenants` in `tests/test_api_auth.py`.

### D. Telco Tenant Verification
- Executed `GET /v1/recommendations/7590-VHVEG?top_n=5` with public key `pk-telco-xxxx`.
- Result: Returned 5 telecom core & add-on products (`InternetService_Fiber`, `MultipleLines`, `PhoneService`, `DeviceProtection`, `OnlineSecurity`). Zero phones, laptops, or audio products returned.
- Verified `Path("data/catalog/telco_default/catalog.csv").exists() == False`.

### E. Verification Suite Exact Totals
- **Pytest Full Suite (`pytest tests/ -q`):** 430 passed, 0 failures, 0 guard violations.
- **Frontend Linter (`npm run lint`):** 16 warnings, 0 errors.
- **Frontend Production Build (`npm run build`):** Built successfully in 1.37s (`dist/index.html` 0.93 kB, `dist/assets/index-DzKvr4YD.css` 8.36 kB, `dist/assets/index-BSi05Ez2.js` 857 kB).
- **Playwright Browser Suite (`scripts/verify_s2_browser.py`):** 8/8 assertions passed across viewports 390x844, 360x800, and 1280x900.


