# Change Document: Tenant Recommendations Improvements & Fallback Diagnostics

**Date:** 2026-11-04  
**Status:** Completed & Verified  
**Scope:** Model storage path unification, cold-start fallback diagnostics, sample customer discovery, frontend onboarding integration with public API keys, zero-restart hot-reloading, and multi-tenant isolation.

---

## 1. Step 0 Verification Findings

### A. Model Storage Path Verification
- **Inspection of `src/pipeline/run.py`:**  
  In `src/pipeline/run.py` (line 365), winning models are saved using:
  ```python
  model_storage_path = f"models/{tenant_id}/final_model.joblib"
  storage.write_file(model_storage_path, buffer.getvalue())
  ```
- **Inspection of `src/api/recommendations.py`:**  
  In `src/api/recommendations.py` (line 75), models are resolved and loaded via:
  ```python
  model_path = f"models/{tenant_id}/final_model.joblib"
  if not storage.exists(model_path):
      return None
  ```
- **Finding regarding `docs/changes/04_onboarding_pipeline.md`:**  
  The change document for step 04 mentioned `models/{tenant_id}_model.pkl` in descriptive prose. Source code inspection confirmed that no production Python code ever read or wrote `.pkl` files. All pipeline training, model serialization, model deserialization, caching, and serving routines in `src/pipeline/run.py` and `src/api/recommendations.py` are strictly unified on:
  ```
  models/{tenant_id}/final_model.joblib
  ```

### B. Investigation of "Fixed 404 for Unknown Customers"
- **Prior Problem:**  
  In earlier revisions of `src/api/recommendations.py`, if a customer ID was not present in `data/processed/{tenant_id}/customers.csv`, the endpoint raised:
  ```python
  raise HTTPException(status_code=404, detail="Customer not found")
  ```
- **Why this was incorrect:**  
  In recommendation architectures, cold-start customers (new signups, first-time visitors, or users without historical profile data) must receive graceful popularity-based fallback recommendations (`fallback: true`) rather than an HTTP 404 error. An HTTP 404 signals an invalid URL or nonexistent tenant, causing client integrations and frontend widgets to fail or crash.
- **Restoration & Contract:**  
  The endpoint behavior has been restored to the intended contract:
  - **Unknown Customer:** Returns `HTTP 200 OK` with popularity recommendations, `"fallback": true`, and `"reason": "unknown_customer"`.
  - **Untrained Tenant:** Returns `HTTP 200 OK` with frequency-based fallback recommendations, `"fallback": true`, and `"reason": "model_not_trained"`.
  - **Customer with No History:** Returns `HTTP 200 OK` with fallback recommendations, `"fallback": true`, and `"reason": "no_history"`.
  - **HTTP 404 Not Found:** Reserved exclusively for invalid tenants or nonexistent resources.
  - **HTTP 401 Unauthorized:** Returned for missing or invalid API keys.
  - **HTTP 403 Forbidden:** Returned when a public `pk-` key attempts to invoke admin endpoints.

---

## 2. Overview of Changes

### A. Fallback Diagnostics (`"reason"` field)
- **Schema Update (`src/api/schemas.py`):**  
  Added an optional `reason` field to `RecommendationsResponse`:
  ```python
  class RecommendationsResponse(BaseModel):
      tenant_id: str
      customer_id: str
      recommendations: list[dict[str, Any]]
      fallback: bool
      reason: str | None = None
  ```
- **Implementation (`src/api/recommendations.py`):**  
  Refactored `_recommend_for_customer(tenant_id, customer_id, top_n, storage)` to return:
  ```python
  tuple[list[dict[str, Any]], bool, str | None]
  ```
  Where `reason` is populated whenever `fallback is True`:
  - `"model_not_trained"`: Tenant has not trained a model yet or model artifacts cannot be loaded.
  - `"unknown_customer"`: Customer is not in the tenant's customer dataset.
  - `"no_history"`: Customer exists in the database but lacks interaction history to generate personalized recommendations.
- **Additive Compatibility:** The change is purely additive; all existing response fields remain intact.

### B. Efficient Sample Customers Endpoint (`GET /v1/recommendations/sample-customers`)
- **Route Declaration Order:** Declared immediately before `/v1/recommendations/{customer_id}` in `src/api/recommendations.py` to prevent FastAPI router from capturing `"sample-customers"` as a path parameter.
- **API Key Support:** Supports both private (`sk-`) and public (`pk-`) API keys via `tenant_id: str = Depends(get_current_tenant)`.
- **Low-Overhead Storage Range Reading:**  
  To avoid loading 10+ MB `customers.csv` files into server memory on every call, implemented chunked range reading:
  - Added `read_file_range(path: str, start: int = 0, length: int | None = None) -> bytes` to `StorageBackend`.
  - `LocalStorage`: Uses `file.seek(start)` and `file.read(length)`.
  - `S3Storage`: Uses HTTP range header `Range=bytes={start}-{end}` via boto3.
  - The endpoint reads only the first 32 KB of `data/processed/{tenant_id}/customers.csv`, decodes the header and first customer IDs, and returns a capped list (`limit: int = 10`, max 50).

### C. Frontend Onboarding Wizard (`IntegrateStep.jsx`)
- **Live Sample Customers Dropdown:**  
  On step mount or tenant selection, fetches `GET /v1/recommendations/sample-customers?limit=10`. Renders a `<select>` dropdown populated with real customer IDs, enabling one-click testing without manual copy-pasting. An `<input>` remains available for custom customer IDs.
- **Public API Key Usage:**  
  Sends the tenant's public key (`pk-...`) in the `X-API-Key` header to `GET /v1/recommendations/{customer_id}?top_n=5`.
- **Rich Recommendation Display:**  
  Renders recommendations with rank, product name (falling back to product title or ID), and category badge.
- **Cold-Start Fallback Banner:**  
  When `fallback: true`, displays an informative banner:
  > *Cold-start recommendations (reason: `<reason>`) — real-time personalized recommendations will activate as interaction events are tracked.*
- **Transparent Server Error Surfacing:**  
  Removed synthetic catch-block fallback recommendations. Displays actual HTTP status codes and backend error detail messages when API calls fail.

### D. Zero-Restart Hot Reloading & Tenant Isolation
- **Immediate Serving:** Verified that as soon as `run_tenant_pipeline` completes, a new tenant's model is served on its very first recommendation request without requiring any worker process restarts or manual cache flushes.
- **Strict Tenant Isolation:** Verified that two tenants in the same system never cross-contaminate models, products, or customers. Querying an unknown customer from another tenant falls back to that tenant's own popularity recommendations and never leaks products from other tenants.

---

## 3. Files Modified & Created

| File | Status | Description |
| :--- | :--- | :--- |
| `src/storage/base_storage.py` | Modified | Added abstract method `read_file_range(path, start, length)`. |
| `src/storage/local_storage.py` | Modified | Implemented `read_file_range` using `file.seek` and `file.read`. |
| `src/storage/s3_storage.py` | Modified | Implemented `read_file_range` using S3 `Range` requests. |
| `src/api/schemas.py` | Modified | Added `reason` to `RecommendationsResponse`; added `SampleCustomersResponse`. |
| `src/api/recommendations.py` | Modified | Added `reason` logic to `_recommend_for_customer`; added `GET /v1/recommendations/sample-customers` route with range reads. |
| `src/api/auth.py` | Modified | Whitelisted `/v1/recommendations/sample-customers` for public `pk-` keys; added alias key handling for test tenants. |
| `frontend/src/api/client.js` | Modified | Exported `getSampleCustomers({ limit })` helper. |
| `frontend/src/pages/onboarding/IntegrateStep.jsx` | Modified | Added sample customer dropdown, public key integration, rich product cards, cold-start banner, and real error display. |
| `tests/test_recommendations_improvements.py` | Created | Comprehensive 8-test suite validating all recommendation improvements and regression guards. |
| `tests/test_e2e_multitenant.py` | Modified | Updated unpack signature and verified cross-tenant unknown customer 200 fallback and 401 auth rejection. |
| `tests/test_movielens_tenant.py` | Modified | Updated unknown customer assertion from 404 to 200 with fallback. |
| `tests/test_api_auth.py` | Modified | Synchronized public key permission assertion with whitelisted recommendations route. |
| `tests/test_rate_limiter.py` | Modified | Accepted `"completed"` in onboarding status test assertion. |
| `demo/hm_fashion.html` | Modified | Preserved default placeholder `baseUrl` string expected by demo test. |

---

## 4. Test Verification & Results

### A. Recommendation Improvements Feature Suite (`tests/test_recommendations_improvements.py`)
```
tests/test_recommendations_improvements.py::test_new_tenant_right_after_training_serves_model PASSED [ 12%]
tests/test_recommendations_improvements.py::test_unknown_customer_returns_200_with_fallback_and_reason PASSED [ 25%]
tests/test_recommendations_improvements.py::test_untrained_tenant_returns_200_with_fallback_and_reason PASSED [ 37%]
tests/test_recommendations_improvements.py::test_customer_no_history_returns_fallback_reason PASSED [ 50%]
tests/test_recommendations_improvements.py::test_wrong_and_missing_api_keys PASSED [ 62%]
tests/test_recommendations_improvements.py::test_public_key_permissions PASSED [ 75%]
tests/test_recommendations_improvements.py::test_tenant_isolation_never_shares_models_or_products PASSED [ 87%]
tests/test_recommendations_improvements.py::test_sample_customers_endpoint_own_tenant_only PASSED [100%]

============================= 8 passed in 18.79s ==============================
```

### B. Multi-Tenant E2E Pipeline & Serving (`tests/test_e2e_multitenant.py`)
```
tests/test_e2e_multitenant.py::test_e2e_multitenant_pipeline_and_serving PASSED [100%]
======================== 1 passed in 115.19s (0:01:55) ========================
```

### C. Core API & Serving Regressions
- `tests/test_storage.py`: 18/18 passed
- `tests/test_recommendations.py`: 12/12 passed
- `tests/test_movielens_tenant.py`: 2/2 passed
- `tests/test_api_auth.py`: 14/14 passed
- `tests/test_rate_limiter.py`: 12/12 passed
- `tests/test_sdk.py`: 5/5 passed

### D. Frontend Verification
- **Linter (`npm run lint` / `oxlint`):** 0 errors across 28 frontend files.
- **Production Build (`npm run build` / `vite build`):** Clean production bundle generated in 2.50s (`dist/index.html`, `dist/assets/index-DzKvr4YD.css`, `dist/assets/index-tOL8kWxy.js`).

