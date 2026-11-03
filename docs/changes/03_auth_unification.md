# Change Document: Authentication Unification & Atomic Persistence

**Date:** 2026-11-03  
**Status:** Completed & Verified  
**Scope:** Unified authentication for administrative endpoints, session JWT vs. API Key resolution, atomic file persistence, enhanced key entropy, and profile security.

---

## 1. Overview of Changes

### A. Unified Administrative Authentication (`get_tenant_for_admin_action`)
- **Problem Resolved:** The frontend React application authenticates by sending session JWTs via `Authorization: Bearer <token>`, but the backend `/v1/onboard/*` endpoints were guarded by `Depends(get_current_tenant)`, which strictly required an `X-API-Key` header and immediately failed with `401: API key is missing`.
- **Implementation:** Added `get_tenant_for_admin_action` in `src/api/auth.py`. This dependency accepts either:
  1. **A private API key (`sk-...`)** passed in the `X-API-Key` header. Public API keys (`pk-...`) are rejected with `403 Forbidden` (`"Forbidden: Public API keys (pk-...) cannot perform administrative or onboarding actions."`).
  2. **A valid session JWT** passed via `Authorization: Bearer <token>` or `X-Session-Token`. Follows the same verification logic as `src/accounts/session.get_current_account`:
     - Rejects MFA challenge tickets (`token_type: "mfa_challenge"`) with `401 Unauthorized`.
     - Validates account existence and activity in storage.
     - Enforces email verification: if `ENFORCE_EMAIL_VERIFICATION=true`, accounts with `email_verified=False` receive `403 Forbidden`.
     - Resolves the `tenant_id` exclusively from the authenticated account's record, never from caller-supplied parameters.
- **Router Rate Limiting Fix:** Updated `check_rate_limit(scope="onboarding")` in `src/api/rate_limiter.py` to use `get_tenant_for_admin_action` instead of defaulting to `get_current_tenant`. This unblocks JWT-authenticated requests at the router dependency boundary before reaching endpoint handlers.
- **Endpoint Protection:** Updated all `/v1/onboard/*` endpoints (`/upload`, `/validate`, `/confirm`, `/train`, `/status`, and `/register-key`) in `src/api/onboarding.py` to depend on `get_tenant_for_admin_action`.
- **Tenant Isolation:** Enforced tenant isolation in `/confirm` and `/register-key`: non-admin callers attempting to configure or register keys for tenants other than their authenticated tenant receive `403 Forbidden`.
- **Unchanged Public Endpoints:** Preserved existing `get_current_tenant` and `get_public_key_tenant` dependencies unchanged for recommendation (`/v1/recommendations`) and event tracking (`/v1/track`) endpoints.

### B. Atomic YAML Persistence (`src/utils/atomic_yaml.py`)
- Created `src/utils/atomic_yaml.py` providing:
  - `atomic_dump_yaml(target_path, data, sort_keys=False, default_flow_style=False, acquire_lock=True)`: Writes YAML data to a temporary file in the target directory (`.{filename}.<tmp>.tmp`), flushes and fsyncs to storage, closes the file descriptor, and executes an atomic `os.replace` onto the target destination. Includes a retry backoff loop on Windows `PermissionError` to handle transient indexing or filesystem locks.
  - `get_thread_lock(path)`: Provides a process-wide `threading.Lock` per resolved filesystem path.
  - `file_lock(lock_path, timeout=10.0)`: OS-level atomic lockfile using `os.O_CREAT | os.O_EXCL` for cross-process safety, with stale lock detection (>60s).
  - `atomic_yaml_write_lock(target_path)`: Combines the process-level thread lock and the cross-process lockfile into a single context manager.
- Integrated atomic persistence across all local YAML writers:
  - `src/utils/key_manager.py`: `issue_tenant_keys()` and `revoke_tenant_keys()`.
  - `src/accounts/storage.py`: `save_account_record()`. Also synchronized reads with `get_thread_lock()`.
  - `scripts/onboard_tenant.py`: `save_tenant_to_config()`.
  - `src/api/onboarding.py`: `register_tenant_key()`.
- **PyYAML Limitation Note:** `ruamel.yaml` is not an installed dependency in this environment. As a result, writing to `config/config.yaml` uses standard `yaml.safe_dump` which preserves structure and values but does not retain comment blocks.

### C. Key Entropy & Fallback Removal
- **Entropy Increased:** Updated `issue_tenant_keys()` in `src/utils/key_manager.py` to generate keys using `secrets.token_hex(16)` (32 hex characters / 128-bit cryptographic entropy) while preserving the `"sk-<tenant>-"` and `"pk-<tenant>-"` prefixes. Existing keys with 6-byte hex suffixes remain fully valid.
- **Removed Fabricated Wildcards:**
  - `src/accounts/service.py:get_account_me_profile()`: Removed `or f"pk-{tenant_id}-xxxx"`. If no public key exists for an account, it raises `AccountError` (mapped to HTTP 409 Conflict in `src/api/accounts.py`).
  - `src/api/onboarding.py`: Removed `f"sk-{t}-xxxx"` fallback in `list_tenant_keys` and `register_tenant_key`. Missing keys return a clear HTTP 400 error.
- **Production Safety:** `get_key_record()` in `src/api/auth.py` strictly rejects any `"-xxxx"` keys when `ENV` or `AI_POD_ENV` is set to `production` or `prod`.

### D. Enriched Profile Endpoint (`GET /v1/accounts/me`)
- Updated `AccountMeResponse` in `src/api/accounts.py` and `get_account_me_profile()` in `src/accounts/service.py` to return:
  - `tenant_id: str`
  - `company_name: str`
  - `email: str`
  - `public_key: str | None`
  - `key_created_at: str | None`
  - `has_private_key: bool`
  - `email_verified: bool`
  - `mfa_enabled: bool`
  - `is_admin: bool`
  - `role: str`
  - `created_at: str | None`
- The private API key is strictly omitted from responses and never exposed.

---

## 2. Files Modified & Created

| File | Status | Description |
| :--- | :--- | :--- |
| `src/utils/atomic_yaml.py` | Created | Atomic YAML write utilities (`atomic_dump_yaml`), threading locks (`get_thread_lock`), and cross-process lockfiles (`file_lock`, `atomic_yaml_write_lock`). |
| `src/api/auth.py` | Modified | Added `get_tenant_for_admin_action` supporting private `sk-` keys and session JWTs; rejects `pk-` keys with 403; rejects MFA tickets with 401; enforces email verification; derives tenant strictly from credentials. |
| `src/api/rate_limiter.py` | Modified | Updated `check_rate_limit(scope="onboarding")` to use `get_tenant_for_admin_action`. |
| `src/api/onboarding.py` | Modified | Replaced `get_current_tenant` with `get_tenant_for_admin_action` on `/upload`, `/validate`, `/confirm`, `/train`, `/status`, and `/register-key`. Enforced tenant isolation and removed `"-xxxx"` fallback key fabrication. |
| `src/utils/key_manager.py` | Modified | Upgraded key entropy to `secrets.token_hex(16)`. Switched YAML writes to `atomic_dump_yaml` and `atomic_yaml_write_lock`. |
| `src/accounts/storage.py` | Modified | Switched local account persistence to `atomic_dump_yaml` and `atomic_yaml_write_lock`. Protected reads with `get_thread_lock`. |
| `scripts/onboard_tenant.py` | Modified | Switched `save_tenant_to_config` to `atomic_dump_yaml` and `atomic_yaml_write_lock`. |
| `src/accounts/service.py` | Modified | Extended `get_account_me_profile` with `has_private_key` and `key_created_at`; removed fabricated fallback `pk-...-xxxx`. |
| `src/api/accounts.py` | Modified | Updated `AccountMeResponse` schema to include `has_private_key` and `key_created_at`. Handled missing key errors with HTTP 409. |
| `src/utils/config.py` | Modified | Protected local `tenants_auth` file reads with `get_thread_lock`. |
| `tests/test_auth_unification.py` | Created | Comprehensive test suite covering unified admin auth, key types, MFA tickets, email enforcement, atomic writes, concurrent signups, and profile schema. |

---

## 3. Test Verification & Results

### Suite 1: `tests/test_auth_unification.py` (New Suite)
Command: `.\venv\Scripts\python.exe -m pytest tests/test_auth_unification.py -v`

| Test Name | Result | What It Verifies |
| :--- | :---: | :--- |
| `test_onboarding_accepts_private_sk_key` | **PASSED** | Private `sk-` key succeeds on `/v1/onboard/status`. |
| `test_onboarding_rejects_public_pk_key_with_403` | **PASSED** | Public `pk-` key is rejected on `/v1/onboard/*` with HTTP 403 Forbidden. |
| `test_onboarding_rejects_mfa_ticket_with_401` | **PASSED** | MFA challenge ticket (`token_type: "mfa_challenge"`) is rejected with HTTP 401. |
| `test_onboarding_accepts_jwt_for_owner_tenant_only` | **PASSED** | Session JWT is accepted for tenant actions; cross-tenant `/confirm` and `/register-key` are blocked with HTTP 403. |
| `test_onboarding_enforces_email_verification_when_enabled` | **PASSED** | With `ENFORCE_EMAIL_VERIFICATION=true`, unverified JWT receives HTTP 403 until email is verified. |
| `test_regenerate_keys_invalidates_old_immediately_and_new_work` | **PASSED** | Old keys immediately return HTTP 401; new keys work immediately without server restart. |
| `test_atomic_write_survives_simulated_crash` | **PASSED** | Exception during safe_dump leaves the existing file completely intact and uncorrupted; leaves zero temp files. |
| `test_concurrent_signups_do_not_corrupt_files` | **PASSED** | 8 concurrent threads signing up simultaneously do not corrupt `accounts.local.yaml` or `tenants_auth.local.yaml`. |
| `test_get_accounts_me_returns_all_required_fields` | **PASSED** | Returns `tenant_id`, `public_key`, `email_verified`, `mfa_enabled`, `is_admin`, `key_created_at`, `has_private_key`, and strictly omits `private_key`. |

**Result:** `9 passed in 27.25s`

---

### Suite 2: Existing Test Suites
Commands:
`.\venv\Scripts\python.exe -m pytest tests/test_auth_hardening.py -v`  
`.\venv\Scripts\python.exe -m pytest tests/test_accounts.py -v`

- `tests/test_auth_hardening.py`: **12 passed** (100%)
- `tests/test_accounts.py`: **15 passed** (100%)

---

## 4. Behavior Changes

1. **Frontend Onboarding Unblocked:** The React web frontend (which stores session JWTs in `aipod_token`) can now successfully make requests to `/v1/onboard/*` endpoints. It no longer fails with `401: API key is missing`.
2. **Strict Public Key Boundaries:** Public API keys (`pk-...`) cannot be used to trigger or inspect onboarding, training, validation, or file uploads (HTTP 403). They remain restricted to `POST /v1/track` and `GET /v1/recommendations`.
3. **Crash-Resilient Writes:** Server crashes, power cuts, or process interruptions during account signups, key issuances, or onboarding confirmations will not leave truncated or corrupted YAML files on disk.
4. **No Demo Key Leaks in Production:** Missing keys no longer fall back to generating synthetic `"-xxxx"` keys. Missing keys return explicit 400 or 409 errors.

