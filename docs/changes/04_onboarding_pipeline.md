# Change Document: End-to-End Onboarding Pipeline & Multi-Worker Storage Engine

**Date:** 2026-11-03  
**Status:** Completed & Verified  
**Scope:** Reusable tournament training pipeline, pure storage abstraction across Local & S3, multi-worker safety & cache invalidation, production startup checks, and real backend-driven frontend onboarding wizard.

---

## 1. Overview of Changes

### A. Reusable Tournament Pipeline (`src/pipeline/run.py` & `scripts/run_pipeline.py`)
- **Pipeline Extraction:** Extracted the complete multi-model recommendation tournament from `scripts/run_pipeline.py` into a reusable module function:
  ```python
  def run_tenant_pipeline(
      tenant_id: str,
      storage: StorageBackend | None = None,
      progress_callback: Callable[[dict], None] | None = None,
      config: dict | None = None
  ) -> dict
  ```
- **Tournament Candidates:** Evaluates 4 candidate models:
  1. `ContentBasedRecommender` (TF-IDF + Cosine Similarity on product metadata)
  2. `CollaborativeFilteringRecommender` (TruncatedSVD matrix factorization)
  3. `HybridRecommender` (Ensemble weighting)
  4. `LearnedRankingRecommender` (XGBoost pointwise / pairwise ranker)
- **Candidate Fault-Tolerance:** Each candidate training & evaluation step is wrapped in isolated exception handlers. If a candidate cannot train on small or sparse matrices (e.g. `TruncatedSVD` requiring $\ge 2$ features on minimal test fixtures), that model is marked `"failed"` while viable candidates continue the tournament.
- **Evaluation & Refit:** Computes `NDCG@5`, `Precision@5`, and `Recall@5` on customer-aware train/test splits. Selects the winner by highest `NDCG@5`, refits the winning model on the 100% full dataset, serializes the artifact, clears the in-memory `MODEL_CACHE`, and verifies that all artifacts and processed CSVs exist in storage and deserialize cleanly.
- **CLI Refactoring:** `scripts/run_pipeline.py` was refactored into a thin CLI wrapper over `run_tenant_pipeline`, preserving all flags (`--tenant`, `--data-dir`, `--config`), real-time console progress output, and exit codes.

### B. Pure Storage Routing (`LocalStorage` and `S3Storage`)
- **Direct Filesystem Bypass Eliminated:** Eliminated all direct `resolve_path` file operations for tenant data across the entire onboarding lifecycle:
  - `/v1/onboard/upload`: Streams raw file uploads directly to `data/raw/{tenant_id}_raw.csv` via `StorageBackend.write_file()`.
  - `/v1/onboard/validate` & `GenericConfigAdapter`: Reads raw datasets directly from `StorageBackend.read_file()`, enabling seamless S3 support.
  - `/v1/onboard/confirm`: Writes candidate config (`config/candidate_{tenant_id}.yaml`) and adapted CSVs (`interactions.csv`, `products.csv`, `customers.csv`) via `StorageBackend`.
  - `/v1/onboard/train` & `/v1/onboard/status`: Status files (`status/{tenant_id}.json`) and serialized model artifacts (`models/{tenant_id}_model.pkl`) read/written strictly through `StorageBackend`.
- **Atomic Local Persistence:** Enhanced `LocalStorage.write_file()` with atomic temporary file staging (`.{filename}.<tmp>.tmp`), flush, `os.fsync`, and atomic `os.replace` (including a retry backoff loop for Windows file-locking quirks).
- **Dual Cloud/Local Support:** Fully verified for both `STORAGE_BACKEND=local` and `STORAGE_BACKEND=s3` (via AWS S3 or mocked Moto test environments).

### C. Multi-Worker Safety & Model Cache Invalidation
- **Version Markers (`StorageBackend.get_version_marker`):** Added `get_version_marker(path: str) -> str | None` to the storage abstraction:
  - `LocalStorage`: Returns `{mtime_ns}:{size}` using `os.stat`.
  - `S3Storage`: Returns `{ETag}:{LastModified}` via `s3_client.head_object`.
- **Worker Cache Reloading:** In `src/api/recommendations.py:get_model_for_tenant`, worker processes check the model's version marker every 30 seconds. If a new model artifact was published by another worker or pipeline job, the cache is automatically invalidated and reloaded without requiring worker restarts.
- **Concurrency & Collision Guard:**
  - In `src/api/onboarding.py:train_recommender`, prevents concurrent training jobs across threads and multi-worker processes.
  - Returns `HTTP 409 Conflict` if an active thread is alive or if `status/{tenant_id}.json` indicates `"running"` and `updated_at` is $< 15$ minutes old.
- **Stalled Pipeline Detection:**
  - If a training job crashed silently or a worker died, `/v1/onboard/status` detects when `status == "running"` and `updated_at` is $> 15$ minutes old, automatically returning `"status": "stalled"`.
  - Unstarted tenants receive `HTTP 200` with `{"status": "not_started", "ready": false}` instead of 404/500 errors.
- **Memory Safety:** `run_tenant_pipeline` catches `MemoryError` and explicitly updates the status message to `"dataset is too large for this server's memory"`.

### D. Production Startup Enforcement
- **Lifespan Security Check:** Updated `lifespan(app)` in `src/api/app.py`:
  - When `ENV` or `AI_POD_ENV` is set to `"production"` or `"prod"`, a missing or empty `JWT_SECRET_KEY` immediately raises `RuntimeError("JWT_SECRET_KEY must be set in production environment")`, halting server startup.
  - In development/test environments, logs a prominent warning advising developers to set `JWT_SECRET_KEY`.

### E. Frontend Onboarding Wizard Overhaul
- **`TrainingStep.jsx` (Real Polling & Real Results):**
  - Deleted all simulated `setInterval` progress-bar stepping, the 12-second demo timeout, and hardcoded winner metrics.
  - Implements real 2.5-second polling of `GET /v1/onboard/status`.
  - Displays dynamic status cards for each tournament model (`content`, `collaborative`, `hybrid`, `xgboost`) reflecting backend states (`queued`, `training`, `evaluating`, `done`, `failed`).
  - Displays real evaluation metrics (`NDCG@5`, `Precision@5`, `Recall@5`) for the winning model once training completes.
  - Renders real error messages and a "Retry Training" button on `"failed"` or `"stalled"` statuses. Polling automatically ceases on terminal states or component unmount.
- **`IntegrateStep.jsx` (Accurate Key & Error States):**
  - Removed placeholder `'pk-live-xxxx...'` and `'sk-live-xxxx...'` fallbacks. If keys are missing, displays `'Key not available, regenerate in Dashboard > API Keys'`.
  - Removed mock-recommendations fallback in catch blocks; surfaces actual HTTP error status and detail text.
- **`SchemaStep.jsx` & `ConfirmStep.jsx`:**
  - Removed silent error swallowing and premature auto-navigation; surfaces `err.detail || err.message` to the user.
- **`SignIn.jsx` (Onboarding vs Dashboard Navigation):**
  - Upon successful non-admin sign-in, checks `GET /v1/onboard/status`. If status is `"not_started"` or no model is ready, navigates to `/onboarding/upload`; otherwise directs to `/dashboard`.

---

## 2. Files Modified & Created

| File | Status | Description |
| :--- | :--- | :--- |
| `src/pipeline/__init__.py` | Created | Module init exposing `run_tenant_pipeline`. |
| `src/pipeline/run.py` | Created | Core tournament pipeline training 4 models, scoring NDCG@5, refitting winner, and managing progress callbacks & storage. |
| `scripts/run_pipeline.py` | Modified | Refactored into a thin CLI wrapper around `run_tenant_pipeline`. |
| `src/storage/base_storage.py` | Modified | Added abstract method `get_version_marker(path: str) -> str | None`. |
| `src/storage/local_storage.py` | Modified | Implemented atomic `write_file` (temp staging, flush, fsync, `os.replace`) and `get_version_marker`. |
| `src/storage/s3_storage.py` | Modified | Implemented `get_version_marker` using S3 `head_object` (`ETag:LastModified`). |
| `src/api/schemas.py` | Modified | Enhanced `OnboardStatusResponse` schema with `ready: bool`, `stage`, `models`, `metrics`, `winner_model`, `winner_key`, `dataset`, and extra-field allowance. |
| `src/api/app.py` | Modified | Added production `JWT_SECRET_KEY` check to startup lifespan. |
| `src/api/recommendations.py` | Modified | Added multi-worker cache invalidation via 30s version marker TTL; made `request: Request = None` optional for programmatic calls; fixed 404 for unknown customers. |
| `src/api/onboarding.py` | Modified | Pure storage routing for uploads/validation/training; 15-minute 409 conflict guard; 15-minute stalled detection; server console logging per stage. |
| `frontend/src/pages/onboarding/TrainingStep.jsx` | Modified | Replaced simulation with real 2.5s polling, dynamic model cards, metric displays, and stalled/failed retry controls. |
| `frontend/src/pages/onboarding/IntegrateStep.jsx` | Modified | Removed fallback keys and mock recommendation catch blocks; surfaces real backend errors. |
| `frontend/src/pages/onboarding/SchemaStep.jsx` | Modified | Removed error swallowing; surfaces backend validation errors. |
| `frontend/src/pages/onboarding/ConfirmStep.jsx` | Modified | Removed error swallowing; surfaces backend confirm errors. |
| `frontend/src/pages/SignIn.jsx` | Modified | Added onboarding status check on signin to route to `/onboarding/upload` or `/dashboard`. |
| `tests/test_pipeline_s3_e2e.py` | Modified | Added `DummyModel` test fixture and verified end-to-end tournament execution on mocked S3 storage. |
| `tests/test_onboarding_pipeline_e2e.py` | Created | Comprehensive E2E test suite covering local E2E lifecycle, S3 E2E lifecycle, stalled status detection, multi-worker cache reload, and production JWT checks. |
| `tests/test_auth_hardening.py` | Modified | Configured `JWT_SECRET_KEY` in production test case to align with new production lifespan requirement. |

---

## 3. Test Verification & Results

### Suite 1: `tests/test_onboarding_pipeline_e2e.py` (New Suite)
Command: `.\venv\Scripts\python.exe -m pytest tests/test_onboarding_pipeline_e2e.py -v`

| Test Name | Result | What It Verifies |
| :--- | :---: | :--- |
| `test_onboarding_lifecycle_local_e2e` | **PASSED** | Upload, validate, confirm, tournament training, and status polling succeed on `STORAGE_BACKEND=local`. |
| `test_onboarding_lifecycle_s3_e2e` | **PASSED** | Full onboarding lifecycle succeeds against mocked S3 storage (`STORAGE_BACKEND=s3`). |
| `test_onboard_status_detects_stalled_job` | **PASSED** | Status files with `"running"` older than 15 minutes are reported as `"stalled"`. |
| `test_multi_worker_cache_invalidation` | **PASSED** | Two independent worker caches detect updated version markers and reload updated model artifacts. |
| `test_production_startup_jwt_secret_enforced` | **PASSED** | Server startup raises `RuntimeError` in `production` when `JWT_SECRET_KEY` is not configured. |

**Result:** `5 passed in 23.36s`

---

### Suite 2: `tests/test_pipeline_s3_e2e.py` (S3 Storage Tournament)
Command: `.\venv\Scripts\python.exe -m pytest tests/test_pipeline_s3_e2e.py -v`

| Test Name | Result | What It Verifies |
| :--- | :---: | :--- |
| `test_pipeline_s3_end_to_end` | **PASSED** | Executes raw data ingestion, adaptation, 4-model tournament, and recommendation verification using Moto S3 storage backend. |

**Result:** `1 passed in 4.77s`

---

### Suite 3: `tests/test_storage.py` (Storage Unit Tests)
Command: `.\venv\Scripts\python.exe -m pytest tests/test_storage.py -v`

**Result:** `16 passed in 1.48s`

---

### Suite 4: Frontend Verification
- **Linter:** `npm --prefix frontend run lint`  
  **Result:** `0 errors, 0 warnings`
- **Production Build:** `npm --prefix frontend run build`  
  **Result:** `built in 731ms (dist/ generated successfully)`

---

### Suite 5: Combined Full Test Suite
Command: `.\venv\Scripts\python.exe -m pytest tests/test_onboarding_pipeline_e2e.py tests/test_auth_unification.py tests/test_auth_hardening.py tests/test_accounts.py tests/test_storage.py tests/test_api_v1.py`

**Result:** `67 passed in 107.41s`

---

## 4. Manual Verification Steps

1. **Start the Backend:**
   ```bash
   .\venv\Scripts\python.exe -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
   ```
2. **Start the Frontend:**
   ```bash
   cd frontend
   npm run dev
   ```
3. **Sign Up & Verify:**
   - Navigate to `http://localhost:5173/signup`.
   - Register a new account (e.g. `test_user@example.com`).
   - Retrieve the verification code from server console logs (or `http://localhost:8000/v1/accounts/dev/last-verification?email=test_user@example.com`).
   - Enter the code on `/verify-email`.
4. **Sign In & Onboarding Flow:**
   - Sign in with verified credentials. The frontend will detect no trained model and route to `/onboarding/upload`.
   - Upload a sample retail CSV (containing `customer_id`, `product_id`, `rating`/`timestamp`).
   - Review inferred schema mappings in `/onboarding/schema` and confirm in `/onboarding/confirm`.
   - On `/onboarding/training`, observe real-time status transitions across the 4 model cards (`queued` $\to$ `training` $\to$ `evaluating` $\to$ `done`).
   - Inspect the winning model card, evaluation metrics (`NDCG@5`, `Precision@5`, `Recall@5`), and proceed to `/onboarding/integrate`.
   - On the integration step, verify the API snippet and test recommendations with live data.

