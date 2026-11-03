# Change Document: Email Verification Hardening

**Date:** 2026-11-03  
**Status:** Completed & Verified  
**Scope:** Security hardening, environment configuration loading, rate limiting, and verification endpoints for the AI_POD multi-tenant recommendation platform.

---

## 1. Overview of Changes

1. **Security & Leak Prevention:**
   - Stripped all `verification_code`, `code`, and `token` fields from API responses across `POST /v1/accounts/signup`, `POST /v1/accounts/resend-verification`, and `POST /v1/accounts/verify-email`.
   - Updated underlying services in `src/accounts/service.py` (`signup_company_account`, `resend_email_verification`) to ensure generated codes are never returned in dictionaries or leaked to callers.
   - Verification codes now strictly reach the recipient via authenticated SMTP dispatch (or console logging in local development).
   - Existing and new automated tests now access verification codes via `src.accounts.verification.RECENT_VERIFICATION_EMAILS` or the dedicated dev-inspection endpoint.

2. **Environment & Dotenv Configuration:**
   - In `src/api/app.py`, ensured `dotenv.load_dotenv(PROJECT_ROOT / ".env")` explicitly resolves and loads the project root `.env` at process startup before any other imports or `os.environ` lookups.
   - Updated `.env.example` to document `ENV`, `JWT_SECRET_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_USE_SSL`, and `ENFORCE_EMAIL_VERIFICATION`.
   - Verified that `.env` is listed in `.gitignore` to prevent credential exposure.

3. **Startup Diagnostics & Email Delivery Logging:**
   - Added startup logging in `lifespan(app)` within `src/api/app.py`:
     - When `SMTP_HOST` is configured: `"Email delivery: SMTP via <host>"`
     - When `SMTP_HOST` is empty: `"Email delivery: CONSOLE ONLY (SMTP_HOST not set)"`
     - When running in production (`ENV` or `AI_POD_ENV` equal to `production` or `prod`) without `SMTP_HOST`: logs an `ERROR` indicating email delivery is disabled.

4. **Dev Verification Endpoint:**
   - Added `GET /v1/accounts/dev/last-verification?email=...` to `src/api/accounts.py`.
   - Returns the latest dispatched code and ISO timestamp from `RECENT_VERIFICATION_EMAILS` for local testing, frontend integration, and automation.
   - Strictly protected against production misuse: returns `404 Not Found` whenever `ENV` or `AI_POD_ENV` is set to `production` or `prod`.
   - Returns `404 Not Found` if no verification record exists for the requested email.

5. **CLI Test Script (`scripts/test_email.py`):**
   - Created `scripts/test_email.py --to <address>`.
   - Loads `.env` from project root and tests the live SMTP configuration (STARTTLS or SSL).
   - Transmits a dual plain-text and HTML test message.
   - Prints detailed operational logs and reports either `[SUCCESS]` (exits 0) or the exact SMTP exception class and diagnostic message (exits 1).

6. **Dual Sliding-Window Resend Rate Limiting:**
   - Implemented thread-safe `EmailResendRateLimiter` in `src/api/rate_limiter.py` and instantiated singleton `EMAIL_RESEND_RATE_LIMITER`.
   - Enforces two distinct sliding windows per email address:
     - **Window 1:** Maximum 1 resend per 60 seconds.
     - **Window 2:** Maximum 5 resends per 3600 seconds (1 hour).
   - When limits are exceeded, `POST /v1/accounts/resend-verification` responds with HTTP 429 (`Too Many Requests`), a descriptive error message, and the standard HTTP `Retry-After: <seconds>` header.
   - Includes `.reset()` capability for deterministic test isolation.

---

## 2. Files Changed

| File | Status | Description |
| :--- | :--- | :--- |
| `src/api/accounts.py` | Modified | Removed `verification_code` from Pydantic response models, integrated resend rate limiter (429 + Retry-After), added `GET /dev/last-verification`. |
| `src/accounts/service.py` | Modified | Removed `verification_code` from return payloads of `signup_company_account` and `resend_email_verification`. |
| `src/api/rate_limiter.py` | Modified | Added thread-safe `EmailResendRateLimiter` with 1/60s and 5/1h sliding windows and `EMAIL_RESEND_RATE_LIMITER` instance. |
| `src/api/app.py` | Modified | Explicitly loaded project-root `.env` before all imports; added email delivery status logging and production error checks in `lifespan`. |
| `.env.example` | Modified | Added `ENV`, `JWT_SECRET_KEY`, and complete SMTP and email verification documentation. |
| `scripts/test_email.py` | Added | CLI tool to send real test emails via active `.env` configuration and print exact SMTP diagnostic output. |
| `tests/test_auth_hardening.py` | Modified | Updated tests to retrieve codes via `RECENT_VERIFICATION_EMAILS`; added tests for security stripping, rate limits, dev endpoint, and startup logs. |
| `tests/test_accounts.py` | Modified | Configured test fixture to prevent SMTP hangs and respect local testing modes. |
| `docs/changes/01_email_backend.md` | Added | This change document. |

---

## 3. Test Results

The unified test suite was executed across `tests/test_accounts.py` and `tests/test_auth_hardening.py`:

```shell
.\venv\Scripts\python.exe -m pytest tests/test_accounts.py tests/test_auth_hardening.py
```

### Result:
```text
============================= test session starts =============================
platform win32 -- Python 3.11.1, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\Projects\AI_POD
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 27 items

tests\test_accounts.py ...............                                   [ 55%]
tests\test_auth_hardening.py ............                                [100%]

============================= 27 passed in 59.18s =============================
```

### Detailed Breakdown of Hardening Tests:
- `test_signup_dispatches_verification_code`: **PASSED** (verifies code is absent from API response, present in in-memory store)
- `test_verify_email_success_and_failure`: **PASSED** (validates 6-digit code verification and rejects invalid codes)
- `test_resend_verification_email`: **PASSED** (verifies fresh code dispatch without returning code in response)
- `test_login_brute_force_lockout`: **PASSED** (5 failed attempts locks account with HTTP 423)
- `test_enforce_email_verification_blocks_unverified_login`: **PASSED** (unverified logins rejected with HTTP 403 when enabled)
- `test_totp_mfa_full_lifecycle`: **PASSED** (TOTP setup, challenge, verification, and recovery)
- `test_production_blocks_wildcard_xxxx_mock_keys`: **PASSED** (mock `-xxxx` keys rejected in production)
- `test_security_responses_contain_no_verification_code`: **PASSED** (verifies no `code`, `token`, or `verification_code` across `/signup`, `/resend-verification`, `/verify-email`)
- `test_resend_verification_rate_limiting_60s`: **PASSED** (verifies 2nd resend within 60s returns HTTP 429 with `Retry-After`)
- `test_resend_verification_rate_limiter_hourly`: **PASSED** (verifies 6th resend within 1 hour returns HTTP 429)
- `test_dev_last_verification_endpoint`: **PASSED** (verifies dev endpoint returns code in development and HTTP 404 in production)
- `test_startup_logging_email_delivery`: **PASSED** (verifies SMTP host log, console-only log, and production error log)

---

## 4. Manual Verification Steps

### A. Testing Outgoing SMTP Email Delivery
Run the new CLI diagnostic tool with your destination email address:
```shell
python scripts/test_email.py --to your_email@example.com
```
**Expected Output:**
```text
Connecting to SMTP host 'smtp.gmail.com:587' (SSL=False, From='your_email@gmail.com')...
[SUCCESS] Test email successfully delivered to 'your_email@example.com' via smtp.gmail.com:587.
```

### B. Testing Dev Inspection Endpoint
1. Start the API server:
   ```shell
   python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
   ```
2. Verify startup log contains:
   ```text
   INFO: src.api.app: Email delivery: SMTP via smtp.gmail.com
   ```
3. Sign up a new test account via `curl`:
   ```shell
   curl -X POST http://127.0.0.1:8000/v1/accounts/signup \
     -H "Content-Type: application/json" \
     -d '{"company_name": "Test Co", "email": "test@example.com", "password": "Password123!"}'
   ```
   *Verify:* The JSON response does **not** contain `verification_code` or `code`.
4. Inspect the dispatched code via the dev endpoint:
   ```shell
   curl http://127.0.0.1:8000/v1/accounts/dev/last-verification?email=test@example.com
   ```
   *Verify:* Returns `{"email": "test@example.com", "code": "...", "sent_at": "..."}` with status 200.

### C. Testing Resend Rate Limiting
1. Trigger a resend:
   ```shell
   curl -X POST http://127.0.0.1:8000/v1/accounts/resend-verification \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com"}'
   ```
   *Verify:* Status 200 OK.
2. Immediately trigger a second resend within 60 seconds:
   ```shell
   curl -i -X POST http://127.0.0.1:8000/v1/accounts/resend-verification \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com"}'
   ```
   *Verify:* Returns HTTP 429 Too Many Requests with header `Retry-After: <seconds>`.

### D. Production Safety Check
1. Start with `ENV=production`:
   ```shell
   $env:ENV="production"; python -m uvicorn src.api.app:app --port 8000
   ```
2. Query the dev endpoint:
   ```shell
   curl -i http://127.0.0.1:8000/v1/accounts/dev/last-verification?email=test@example.com
   ```
   *Verify:* Returns HTTP 404 Not Found.

