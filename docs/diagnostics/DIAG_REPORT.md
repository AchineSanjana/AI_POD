# AI_POD Diagnostic Audit Report

**Audit Target:** AI_POD Multi-Tenant Recommendation Platform  
**Scope:** Email Verification, Frontend-Backend Wiring, API Keys, Model Serving, Dashboard Telemetry, and State on Disk  
**Date:** November 3, 2026  
**Auditor:** Automated Engineering Diagnostics Suite  
**Status:** Complete Audit (Read-Only Analysis)

---

## Table of Contents

1. [Section A: Email Verification Audit](#section-a-email-verification-audit)
2. [Section B: Frontend-Backend Connection & Onboarding](#section-b-frontend-backend-connection--onboarding)
3. [Section C: API Key Lifecycle & Authentication Security](#section-c-api-key-lifecycle--authentication-security)
4. [Section D: Recommendations & Serving for New Tenants](#section-d-recommendations--serving-for-new-tenants)
5. [Section E: Dashboard Data Integrity & Mock Analysis](#section-e-dashboard-data-integrity--mock-analysis)
6. [Section F: Current State on Disk](#section-f-current-state-on-disk)
7. [Root Causes Ranked by Severity](#root-causes-ranked-by-severity)
8. [Files Requiring Review & Remediation](#files-requiring-review--remediation)

---

## Section A: Email Verification Audit

### 1. SMTP Sending vs. In-Memory Fallback Decision Logic

**File:** [`src/accounts/verification.py`](file:///d:/Projects/AI_POD/src/accounts/verification.py)

#### Decision Workflow (Lines 58–150)
1. At line 58, `clean_email = email.strip().lower()`.
2. At lines 62–68, **`RECENT_VERIFICATION_EMAILS` is ALWAYS populated** unconditionally before checking SMTP configuration:
   ```python
   # Lines 62-68 in src/accounts/verification.py
   RECENT_VERIFICATION_EMAILS[clean_email] = {
       "email": clean_email,
       "company_name": company_name,
       "code": code,
       "token": token,
       "sent_at": now_iso,
   }
   ```
3. At line 71, the system checks `smtp_host = os.environ.get("SMTP_HOST", "").strip()`.
   - **If `smtp_host` is truthy (non-empty string):** An external SMTP transmission is attempted inside a `try...except` block (lines 73–141). If successful, `logger.info("Dispatched verification email to '%s' via SMTP (%s:%d)", ...)` runs and returns `True`. If an exception occurs, it logs a warning (line 140) and returns `False`.
   - **If `smtp_host` is missing or empty:** Execution skips the `if smtp_host:` block, lands at lines 143–150, logs the code to the development console (`logger.info("Verification code for '%s' (%s): [%s] (expires in %d min, SMTP not configured)", ...)`), and returns `False`.

#### Environment Variables Read & Behavior When Missing

| Environment Variable | Code Location | Type / Default | Behavior If Missing / Invalid |
| :--- | :--- | :--- | :--- |
| `SMTP_HOST` | Line 71 | `str` (empty default) | If missing or whitespace, SMTP is skipped entirely. Logs to console and falls back to in-memory `RECENT_VERIFICATION_EMAILS`. Returns `False`. |
| `SMTP_PORT` | Line 78 | `int`, default `"587"` | If missing, defaults to `587`. If set to non-integer, raises `ValueError` caught at line 139, logs warning, returns `False`. |
| `SMTP_USE_SSL` | Lines 79–82 | `bool`, default `False` | Checked via `.lower() in ("true", "1", "yes") or port == 465`. If missing, evaluates to `False` (unless port is 465), using `smtplib.SMTP` instead of `smtplib.SMTP_SSL`. |
| `SMTP_USER` | Line 83 | `str | None` | If missing, evaluates to `None`. No `server.login()` is attempted unless both `user and pwd` are truthy. |
| `SMTP_PASS` | Line 84 | `str | None` | If missing, evaluates to `None`. No `server.login()` is attempted unless both `user and pwd` are truthy. |
| `SMTP_FROM` | Line 85 | `str`, fallback | Defaults to `os.environ.get("SMTP_FROM", "").strip() or user or "no-reply@ai-pod.local"`. If missing, uses `SMTP_USER`, or `"no-reply@ai-pod.local"` if `SMTP_USER` is empty. |
| `SMTP_TIMEOUT` | Line 123 | `float`, default `"12.0"` | Connection timeout in seconds. If missing, defaults to `12.0`. If invalid float, raises `ValueError`, logs warning, returns `False`. |
| `SMTP_STARTTLS`| Line 131 | `bool`, default `"true"` | Evaluated when `use_ssl` is False. Defaults to `True`. Calls `server.starttls()`. If set to `"false"`, `starttls()` is bypassed. |

---

### 2. Frontend 6-Digit Code Input & Resend Verification Check

#### Does `frontend/` contain any page, route, or component to enter the 6-digit code?
**NO.** There is no page, modal, or input component in the entire frontend to enter the email verification code:
- [`frontend/src/App.jsx`](file:///d:/Projects/AI_POD/frontend/src/App.jsx#L45-L78): Declares routes `/`, `/features`, `/how-it-works`, `/signup`, `/signin`, `/ui`, `/demo`, `/onboarding/*`, and `/dashboard/*`. There is no `/verify` or `/verify-email` route.
- [`frontend/src/pages/SignUp.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/SignUp.jsx#L45-L51):
  ```javascript
  // Lines 45-51 of SignUp.jsx
  const data = await signup({ company_name: form.company_name, email: form.email, password: form.password });
  localStorage.setItem('aipod_sk', data.private_key);
  localStorage.setItem('aipod_pk', data.public_key);
  authLogin(data.private_key, { company_name: data.company_name, tenant_id: data.tenant_id, public_key: data.public_key, email_verified: data.email_verified });
  navigate('/onboarding/upload');
  ```
  After successful signup, the user is navigated directly to `/onboarding/upload`. The response fields `email_verified` (False) and `verification_code` are ignored by the UI.
- [`frontend/src/pages/SignIn.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/SignIn.jsx#L11-L25): Handles `form.mfa_code` strictly for TOTP two-factor authentication when `data.mfa_required` is True. It does not handle email verification codes.
- [`frontend/src/api/client.js`](file:///d:/Projects/AI_POD/frontend/src/api/client.js#L24-L25): Exports `verifyEmail` and `resendVerification`, but **neither function is imported or called anywhere in `frontend/src/`**.

#### Does `resendVerification()` send the email in its body?
In [`frontend/src/api/client.js`](file:///d:/Projects/AI_POD/frontend/src/api/client.js#L25):
```javascript
export const resendVerification = (body) => request('/accounts/resend-verification', { method: 'POST', body: JSON.stringify(body) });
```
- The function signature is `resendVerification = (body) => ...`. If called without arguments (e.g. `resendVerification()`), `body` is `undefined`, so `JSON.stringify(undefined)` evaluates to `undefined`, sending an empty request body.
- The backend handler in [`src/api/accounts.py`](file:///d:/Projects/AI_POD/src/api/accounts.py#L350-L352) expects `ResendVerificationRequest(email: str)` (lines 135–139). An empty body fails FastAPI Pydantic validation with `422 Unprocessable Entity`.
- Regardless, `resendVerification` is dead code—it is never invoked by any UI component.

---

### 3. Behavior of `SignIn.jsx` on Backend 403 (Email Not Verified)

**File:** [`frontend/src/pages/SignIn.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/SignIn.jsx#L20-L47), [`src/api/accounts.py`](file:///d:/Projects/AI_POD/src/api/accounts.py#L388-L392)

1. When `ENFORCE_EMAIL_VERIFICATION=true` is set on the backend, [`src/accounts/service.py:376-379`](file:///d:/Projects/AI_POD/src/accounts/service.py#L376-L379) raises `EmailNotVerifiedError("Email has not been verified. Please verify your email before logging in.")`.
2. [`src/api/accounts.py:388-392`](file:///d:/Projects/AI_POD/src/api/accounts.py#L388-L392) converts this into an HTTP 403 response:
   ```python
   except EmailNotVerifiedError as exc:
       raise HTTPException(
           status_code=status.HTTP_403_FORBIDDEN,
           detail=str(exc),
       )
   ```
3. In [`frontend/src/api/client.js:16`](file:///d:/Projects/AI_POD/frontend/src/api/client.js#L16), `request()` receives `res.status = 403` and throws `{ status: 403, message: data.detail || 'Request failed' }`.
4. In [`SignIn.jsx:44-46`](file:///d:/Projects/AI_POD/frontend/src/pages/SignIn.jsx#L44-L46):
   ```javascript
   } catch (err) {
     setError(err.message || 'Login failed');
   } finally { setLoading(false); }
   ```
5. In [`SignIn.jsx:94`](file:///d:/Projects/AI_POD/frontend/src/pages/SignIn.jsx#L94):
   ```jsx
   {error && <div className="alert alert-error mb-6">{error}</div>}
   ```
6. **Result:** `SignIn.jsx` merely displays the raw string `"Email has not been verified. Please verify your email before logging in."` in a red banner. It does **not** display a verification code input, does **not** provide a resend link, and does **not** redirect the user. The user is completely stranded.

---

## Section B: Frontend-Backend Connection & Onboarding

### 4. Client API Function Mapping

**File:** [`frontend/src/api/client.js`](file:///d:/Projects/AI_POD/frontend/src/api/client.js)

`BASE_URL` is configured at line 1 as `import.meta.env.VITE_API_URL || '/v1'`. Default in `.env` is `http://localhost:8000/v1`.

| Function Name | Lines | Exact Target URL | Headers Sent | Backend Handler |
| :--- | :--- | :--- | :--- | :--- |
| `signup(body)` | Line 21 | `${BASE_URL}/accounts/signup` | `Content-Type: application/json` (+ Bearer if `aipod_token` in localStorage) | [`src/api/accounts.py:signup`](file:///d:/Projects/AI_POD/src/api/accounts.py#L254) (`POST /accounts/signup`) |
| `login(body)` | Line 22 | `${BASE_URL}/accounts/login` | `Content-Type: application/json` (+ Bearer if token) | [`src/api/accounts.py:login`](file:///d:/Projects/AI_POD/src/api/accounts.py#L375) (`POST /accounts/login`) |
| `loginMfa(body)` | Line 23 | `${BASE_URL}/accounts/login/mfa` | `Content-Type: application/json` (+ Bearer if token) | [`src/api/accounts.py:login_mfa`](file:///d:/Projects/AI_POD/src/api/accounts.py#L425) (`POST /accounts/login/mfa`) |
| `verifyEmail(body)` | Line 24 | `${BASE_URL}/accounts/verify-email` | `Content-Type: application/json` (+ Bearer if token) | [`src/api/accounts.py:verify_email`](file:///d:/Projects/AI_POD/src/api/accounts.py#L328) (`POST /accounts/verify-email`) |
| `resendVerification(body)`| Line 25 | `${BASE_URL}/accounts/resend-verification` | `Content-Type: application/json` (+ Bearer if token) | [`src/api/accounts.py:resend_verification`](file:///d:/Projects/AI_POD/src/api/accounts.py#L350) (`POST /accounts/resend-verification`) |
| `getMe(explicitToken)` | Lines 26–29 | `${BASE_URL}/accounts/me` | `Content-Type: application/json`, `Authorization: Bearer <token>` | [`src/api/accounts.py:me`](file:///d:/Projects/AI_POD/src/api/accounts.py#L538) (`GET /accounts/me`) |
| `regenerateKeys()` | Line 30 | `${BASE_URL}/accounts/keys/regenerate` | `Content-Type: application/json`, `Authorization: Bearer <token>` | [`src/api/accounts.py:regenerate_keys`](file:///d:/Projects/AI_POD/src/api/accounts.py#L560) (`POST /accounts/keys/regenerate`) |
| `mfaSetup()` | Line 33 | `${BASE_URL}/accounts/mfa/setup` | `Content-Type: application/json`, `Authorization: Bearer <token>` | [`src/api/accounts.py:mfa_setup`](file:///d:/Projects/AI_POD/src/api/accounts.py#L448) (`POST /accounts/mfa/setup`) |
| `mfaEnable(body)` | Line 34 | `${BASE_URL}/accounts/mfa/enable` | `Content-Type: application/json`, `Authorization: Bearer <token>` | [`src/api/accounts.py:mfa_enable`](file:///d:/Projects/AI_POD/src/api/accounts.py#L476) (`POST /accounts/mfa/enable`) |
| `mfaDisable(body)` | Line 35 | `${BASE_URL}/accounts/mfa/disable` | `Content-Type: application/json`, `Authorization: Bearer <token>` | [`src/api/accounts.py:mfa_disable`](file:///d:/Projects/AI_POD/src/api/accounts.py#L510) (`POST /accounts/mfa/disable`) |
| `onboardUpload(formData)` | Lines 38–43 | `${BASE_URL}/onboard/upload` | `Authorization: Bearer <token>` (multipart form boundary handled by browser) | [`src/api/onboarding.py:upload_dataset`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L230) (`POST /onboard/upload`) |
| `onboardValidate(body)` | Line 45 | `${BASE_URL}/onboard/validate` | `Content-Type: application/json` (+ Bearer if token) | [`src/api/onboarding.py:validate_dataset`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L344) (`POST /onboard/validate`) |
| `onboardConfirm(body)` | Line 46 | `${BASE_URL}/onboard/confirm` | `Content-Type: application/json` (+ Bearer if token) | [`src/api/onboarding.py:confirm_onboarding`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L405) (`POST /onboard/confirm`) |
| `onboardTrain()` | Line 47 | `${BASE_URL}/onboard/train` | `Content-Type: application/json` (+ Bearer if token) | [`src/api/onboarding.py:train_tenant`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L455) (`POST /onboard/train`) |
| `onboardStatus()` | Line 48 | `${BASE_URL}/onboard/status` | `Content-Type: application/json` (+ Bearer if token) | [`src/api/onboarding.py:get_onboarding_status`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L528) (`GET /onboard/status`) |
| `getRecommendations(customerId, topN)` | Lines 51–54 | `${BASE_URL}/recommendations/${customerId}?top_n=${topN}` | `Content-Type: application/json`, `X-API-Key: <aipod_pk>` (+ Bearer if token) | [`src/api/recommendations.py:get_recommendations_for_customer`](file:///d:/Projects/AI_POD/src/api/recommendations.py#L385) (`GET /recommendations/{customer_id}`) |

> [!CRITICAL]
> **Authentication Mismatch on `/onboard/*`:** Notice that `onboardUpload`, `onboardValidate`, `onboardConfirm`, `onboardTrain`, and `onboardStatus` all send `Authorization: Bearer <token>`. **None of them send `X-API-Key`.** As proven in item 6, the backend handlers require `X-API-Key`, causing every call from the frontend to fail with `401 Unauthorized`.

---

### 5. Mocking & Simulation in `TrainingStep.jsx` and `IntegrateStep.jsx`

#### In `frontend/src/pages/onboarding/TrainingStep.jsx`:

1. **Simulated Model Stepping via `setInterval` (Lines 29–49):**
   ```javascript
   // Lines 29-49 in TrainingStep.jsx
   useEffect(() => {
     if (!started) return;
     if (status === 'running') {
       let step = 0;
       const id = setInterval(() => {
         step++;
         setModelSt(prev => {
           const next = { ...prev };
           if (step === 1) next.content       = 'training';
           if (step === 3) next.collaborative = 'training';
           if (step === 5) next.content       = 'evaluating';
           if (step === 7) { next.hybrid      = 'training'; next.content = 'done'; }
           if (step === 9) { next.xgboost     = 'training'; next.collaborative = 'evaluating'; }
           if (step === 11){ next.collaborative= 'done'; next.hybrid = 'evaluating'; }
           if (step === 13){ next.hybrid      = 'done'; next.xgboost = 'evaluating'; }
           return next;
         });
         if (step >= 13) clearInterval(id);
       }, 800);
       return () => clearInterval(id);
     }
     if (status === 'completed') {
       setModelSt({ content:'done',collaborative:'done',hybrid:'done',xgboost:'done' });
     }
   }, [status, started]);
   ```
2. **Hardcoded Winner Simulation on Polling (Lines 68–75):**
   ```javascript
   // Lines 68-75 in TrainingStep.jsx
   if (d.status === 'completed' && !d.winner_model) {
     // Simulate winner for demo
     setTimeout(() => {
       setWinner('Learned Ranking (XGBoost)');
       setMetrics({ ndcg: 0.607, precision: 0.316, recall: 0.887 });
     }, 2000);
   }
   ```
3. **Forced Completion Timeout After 12 Seconds (Lines 80–90):**
   ```javascript
   // Lines 80-90 in TrainingStep.jsx
   // Simulate completion after 12s if no real backend
   useEffect(() => {
     if (!started) return;
     const id = setTimeout(() => {
       setStatus('completed');
       setWinner('Learned Ranking (XGBoost)');
       setMetrics({ ndcg: 0.607, precision: 0.316, recall: 0.887 });
       clearInterval(pollRef.current);
     }, 12000);
     return () => clearTimeout(id);
   }, [started]);
   ```

#### In `frontend/src/pages/onboarding/IntegrateStep.jsx`:

1. **Fallback Mock Keys (Lines 11–12):**
   ```javascript
   // Lines 11-12 in IntegrateStep.jsx
   const pk = keys.pk || localStorage.getItem('aipod_pk') || 'pk-live-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';
   const sk = keys.sk || localStorage.getItem('aipod_sk') || 'sk-live-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';
   ```
2. **Mock Recommendations Catch Block (Lines 72–84):**
   ```javascript
   // Lines 72-84 in IntegrateStep.jsx
   } catch {
     // Mock response for demo
     setTestResult({
       tenant_id: tenantId || 'demo',
       customer_id: testId,
       recommendations: [
         { rank:1, product_id:'P001', product_name:'Online Security',  category:'Add-on' },
         { rank:2, product_id:'P002', product_name:'Tech Support',      category:'Add-on' },
         { rank:3, product_id:'P003', product_name:'Streaming TV',      category:'Entertainment' },
       ],
       fallback: false,
     });
   }
   ```

---

### 6. End-to-End Audit of `src/api/onboarding.py`

#### A. Where Files Are Written (Absolute Resolved Paths)
1. **`/v1/onboard/upload`** (lines 292–294):
   - Path: `resolve_path(f"data/raw/{tenant_id}_raw.csv")`
   - Absolute: `D:\Projects\AI_POD\data\raw\{tenant_id}_raw.csv`
2. **`/v1/onboard/confirm`** (lines 434–435):
   - Calls `save_tenant_to_config(tenant_id, config_block)` from [`scripts/onboard_tenant.py`](file:///d:/Projects/AI_POD/scripts/onboard_tenant.py#L68).
   - Absolute: `D:\Projects\AI_POD\config\config.yaml`
3. **`_execute_training_job` (Background Worker)**:
   - Status file (lines 60, 82): `storage.write_file(f"status/{tenant_id}.json", payload)`
     - Absolute: `D:\Projects\AI_POD\status\{tenant_id}.json` (or S3 `s3://<bucket>/status/{tenant_id}.json`)
   - Model artifact (lines 180–181): `save_model(model, f"models/{tenant_id}/final_model.joblib", storage=storage)`
     - Absolute: `D:\Projects\AI_POD\models\{tenant_id}\final_model.joblib` (or S3)
4. **`/v1/onboard/register-key`** (lines 725–736):
   - Path: `resolve_path("config/tenants_auth.local.yaml")`
   - Absolute: `D:\Projects\AI_POD\config\tenants_auth.local.yaml`

#### B. Which `tenant_id` Is Used and Where It Comes From
- In every endpoint (`upload`, `validate`, `confirm`, `train`, `status`), the parameter is defined as:
  ```python
  tenant_id: str = Depends(get_current_tenant)
  ```
- Looking at [`src/api/auth.py:213-228`](file:///d:/Projects/AI_POD/src/api/auth.py#L213-L228):
  ```python
  def get_current_tenant(
      request: Request = None,
      x_api_key: str | None = Header(None, alias="X-API-Key"),
  ) -> str:
      if not x_api_key:
          raise HTTPException(
              status_code=401,
              detail="API key is missing. Provide a valid 'X-API-Key' header.",
          )
  ```
- **The dependency strictly requires `X-API-Key`. It never inspects `Authorization: Bearer <token>`.**
- Because the frontend sends only `Authorization: Bearer <token>` in `client.js`, `x_api_key` is `None` on all onboarding requests, immediately raising HTTP 401.

#### C. Does It Write to `config/config.yaml`?
- **YES.** In `/v1/onboard/confirm` line 434, `save_tenant_to_config(tenant_id, config_block)` writes the validated tenant configuration into `config/config.yaml` under `tenants.{tenant_id}`.

#### D. Does It Actually Call the Same Pipeline as `scripts/run_pipeline.py`?
- **NO.**
  - [`scripts/run_pipeline.py`](file:///d:/Projects/AI_POD/scripts/run_pipeline.py#L58-L149) creates a train/test split, fits 4 candidate models (`ContentBasedRecommender`, `CollaborativeFilteringRecommender`, `HybridRecommender`, `LearnedRankingRecommender`), evaluates all 4 using `evaluate_all(recs, relevant, k=5)` (NDCG@5, Precision@5, Recall@5), picks the winner, and refits the winner on the full dataset.
  - [`src/api/onboarding.py:_execute_training_job`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L172-L178) **completely bypasses model evaluation and tournament competition**. It hardcodes the instantiation and training of `LearnedRankingRecommender`:
    ```python
    model = LearnedRankingRecommender(
        customer_specs=specs
    ).fit(
        customers=customers,
        products=products,
        interactions=interactions,
    )
    ```
  - It does not calculate NDCG@5, Precision@5, or Recall@5. It does not write `winner_model` or `metrics` to `status/{tenant_id}.json`.

#### E. What Does the Background Thread Do on Exception?
- Lines 191–202 in [`src/api/onboarding.py`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L191-L202):
  ```python
  except Exception as exc:
      logger.exception("Training failed for tenant %s: %s", tenant_id, exc)
      _save_training_status(
          tenant_id=tenant_id,
          status_val="failed",
          message=f"Training failed for tenant '{tenant_id}': {exc}",
          storage=storage,
          error=str(exc),
      )
  finally:
      _ACTIVE_TRAINING_THREADS.pop(tenant_id, None)
  ```
- It catches `Exception`, logs the full stack trace with `logger.exception`, writes a JSON status file with `status="failed"` and `error=str(exc)`, removes the thread entry from `_ACTIVE_TRAINING_THREADS`, and terminates silently.

---

### 7. Execution Working Directory & Resolved Project Paths

**File:** [`src/utils/config.py`](file:///d:/Projects/AI_POD/src/utils/config.py#L22-L23), [`src/storage/local_storage.py`](file:///d:/Projects/AI_POD/src/storage/local_storage.py#L21-L35)

- In `src/utils/config.py`:
  ```python
  PROJECT_ROOT = Path(__file__).resolve().parents[2]
  DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
  ```
- When resolved from `D:\Projects\AI_POD\src\utils\config.py`:
  - `Path(__file__).resolve()`: `D:\Projects\AI_POD\src\utils\config.py`
  - `parents[0]`: `D:\Projects\AI_POD\src\utils`
  - `parents[1]`: `D:\Projects\AI_POD\src`
  - `parents[2]` (`PROJECT_ROOT`): **`D:\Projects\AI_POD`**
- In `src/storage/local_storage.py:21-35`:
  `LocalStorage.base_dir` defaults to `PROJECT_ROOT.resolve()` (`D:\Projects\AI_POD`). All relative storage paths are anchored to this base directory via `(self.base_dir / rel).resolve()`.

#### Resolved Directory Paths

| Logical Path | Code Resolver | Exact Absolute Filesystem Path |
| :--- | :--- | :--- |
| `data/` | `resolve_path("data")` / `storage._resolve("data")` | `D:\Projects\AI_POD\data` |
| `data/raw/` | `resolve_path("data/raw")` | `D:\Projects\AI_POD\data\raw` |
| `data/processed/` | `storage._resolve("data/processed")` | `D:\Projects\AI_POD\data\processed` |
| `models/` | `storage._resolve("models")` | `D:\Projects\AI_POD\models` |
| `status/` | `storage._resolve("status")` | `D:\Projects\AI_POD\status` |
| `config/` | `resolve_path("config")` | `D:\Projects\AI_POD\config` |

Regardless of the operating system's current working directory (`os.getcwd()`), all file operations are anchored to `PROJECT_ROOT`.

---

## Section C: API Key Lifecycle & Authentication Security

### 8. Key Generation, Formats, Persistence, Atomicity & Caching

**File:** [`src/utils/key_manager.py`](file:///d:/Projects/AI_POD/src/utils/key_manager.py#L19-L156), [`src/accounts/service.py`](file:///d:/Projects/AI_POD/src/accounts/service.py#L257-L265)

#### Key Generation & Format
Generated in `issue_tenant_keys()`:
- **Private Key:** `f"sk-{clean_tenant}-{secrets.token_hex(6)}"` (e.g. `sk-sanjtelco-7b02dfb32cb8`)
- **Public Key:** `f"pk-{clean_tenant}-{secrets.token_hex(6)}"` (e.g. `pk-sanjtelco-0961b1a20dfa`)

#### Persistence Location
- **If `STORAGE_BACKEND=s3`:**
  - If `TENANTS_AUTH_SECRET_NAME` is configured: Persisted in **AWS Secrets Manager** as JSON string.
  - Otherwise: Persisted in **AWS SSM Parameter Store** under `/ai_pod/tenants_auth` (or `TENANTS_AUTH_SSM_PARAM`) with `Type="SecureString"`.
- **If `STORAGE_BACKEND=local`:**
  - Persisted in **`config/tenants_auth.local.yaml`** under top-level key `tenants_auth:`.

#### Atomicity Analysis
- **AWS SSM / Secrets Manager:** Atomic at the API level (single `put_parameter` or `put_secret_value` call).
- **Local Filesystem:** **NOT ATOMIC.** Lines 143–144 of `key_manager.py`:
  ```python
  with open(local_path, "w", encoding="utf-8") as f:
      yaml.safe_dump(data, f, sort_keys=False)
  ```
  `open(..., "w")` truncates the file immediately. It does not write to a temporary file before renaming (`replace()`). A process interruption or concurrent write will corrupt `config/tenants_auth.local.yaml`.

#### Caching vs. Request Loading
- **Cached in memory at startup:** `src/api/auth.py` loads existing records into `TENANT_KEY_RECORDS` and `TENANT_AUTH_MAPPING` at import time via `load_tenant_auth()`.
- **Updated on mutation:** `issue_tenant_keys()`, `regenerate_tenant_keys()`, and `register_tenant_key()` immediately update the in-memory dictionaries `TENANT_KEY_RECORDS` and `TENANT_AUTH_MAPPING`.
- **Cache-miss fallback on request:** When `get_key_record(api_key)` in `src/api/auth.py:113` encounters an unknown key, it re-queries `get_tenant_auth_records()`, reloading from `config/tenants_auth.local.yaml` (or AWS SSM).

---

### 9. Key Suffixes and the Production Block Check

**Files:** [`src/api/auth.py`](file:///d:/Projects/AI_POD/src/api/auth.py#L96-L102), [`src/utils/key_manager.py`](file:///d:/Projects/AI_POD/src/utils/key_manager.py#L54-L60)

#### Can Generated Keys End in `xxxx` or `-xxxx`?
- **Randomly Generated Keys:** Keys generated by `issue_tenant_keys()` use `secrets.token_hex(6)`, which produces 12 lowercase hexadecimal characters (`[0-9a-f]{12}`). The character `'x'` is **not** a valid hexadecimal digit. Therefore, randomly generated keys can **never** naturally contain or end in `xxxx` or `-xxxx`.
- **Fallback Keys in Code:**
  - [`src/accounts/service.py:671`](file:///d:/Projects/AI_POD/src/accounts/service.py#L671):
    ```python
    public_key = get_tenant_public_key(tenant_id, config=cfg) or f"pk-{tenant_id}-xxxx"
    ```
    If `get_tenant_public_key()` returns `None`, it falls back to `pk-{tenant_id}-xxxx`.
  - [`src/api/onboarding.py:692`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L692):
    ```python
    default_sk = f"sk-{t}-xxxx"
    ```
  - [`src/api/onboarding.py:715`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L715):
    ```python
    api_key = payload.api_key.strip() if payload.api_key else f"sk-{tenant_id}-xxxx"
    ```

#### Production Check Behavior in `src/api/auth.py`:
Lines 96–102 of `src/api/auth.py`:
```python
is_prod = os.environ.get("ENV", "").lower() in (
    "production",
    "prod",
) or os.environ.get("AI_POD_ENV", "").lower() in ("production", "prod")
if is_prod and api_key.endswith("-xxxx"):
    return None
```
And lines 129–134:
```python
if is_prod:
    return None
```
**Conclusion:** In any environment where `ENV=production` or `AI_POD_ENV=production`, **any key ending in `-xxxx` is strictly rejected and returns `None` (resulting in HTTP 401)**. If an account has to fall back to `pk-{tenant_id}-xxxx` because of a storage issue, it will be immediately blocked in production.

---

### 10. Tenant Mapping Mechanisms: JWT Session vs. X-API-Key

#### 1. Incoming JWT Session Token -> Tenant ID
**Implementation:** [`src/accounts/session.py:get_current_account`](file:///d:/Projects/AI_POD/src/accounts/session.py#L128-L160)
1. Extracted from header `Authorization: Bearer <token>` or `X-Session-Token: <token>`.
2. Decoded and signature verified via `jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])`.
3. Validates `payload.get("token_type") == "session"` and checks expiration timestamp (`exp`).
4. Extracts `account_id = payload.get("account_id")` and `tenant_id = payload.get("tenant_id")`.
5. Resolves full account record via `get_account_by_id(account_id)`.
6. Dependency is utilized in `src/api/accounts.py` (`/me`, `/keys/regenerate`, `/mfa/*`).

#### 2. Incoming X-API-Key -> Tenant ID
**Implementation:** [`src/api/auth.py:get_current_tenant`](file:///d:/Projects/AI_POD/src/api/auth.py#L213-L248)
1. Extracted from header `X-API-Key: <key>`.
2. Looked up in `TENANT_KEY_RECORDS` / `TENANT_AUTH_MAPPING` in-memory dictionaries.
3. If not found in cache, re-reads `config/tenants_auth.local.yaml` or AWS SSM.
4. If still not found and `ENV != "production"`, checks demo/test fallback patterns (`sk-{tenant}-xxxx`, `pk-{tenant}-xxxx`).
5. Enforces key type restrictions: If `key_type == "public"`, verifies method and path (`POST /v1/track` and `GET /v1/recommendations` allowed; all other routes raise `403 Forbidden`).
6. Returns string `record["tenant_id"]`. Dependency is utilized in `src/api/recommendations.py`, `src/api/tracking.py`, and `src/api/onboarding.py`.

---

## Section D: Recommendations & Serving for New Tenants

### 11. `get_model_for_tenant()`, `MODEL_CACHE` and `config.yaml` Re-reads

**Files:** [`src/api/recommendations.py`](file:///d:/Projects/AI_POD/src/api/recommendations.py#L38-L79), [`src/utils/config.py`](file:///d:/Projects/AI_POD/src/utils/config.py#L98-L100)

#### How `get_model_for_tenant()` Resolves Runtime Tenants
1. Checks `if tenant_id in MODEL_CACHE: return MODEL_CACHE[tenant_id]`.
2. If absent from cache:
   - Initializes storage via `storage = get_storage_backend(config)`.
   - Checks `model_path = f"models/{tenant_id}/final_model.joblib"`.
   - If file exists in storage: deserializes via `persistence_load_model(model_path, storage=storage)`, stores in `MODEL_CACHE[tenant_id]`, and returns model instance.
   - If file does NOT exist: raises `HTTPException(404, detail="No trained model found for tenant '{tenant_id}'. Run the pipeline for this tenant first.")`.

#### Is `config.yaml` Re-read After `onboarding/confirm` or Only at Startup?
- In [`src/utils/config.py:98-100`](file:///d:/Projects/AI_POD/src/utils/config.py#L98-L100):
  ```python
  def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
      with open(config_path, "r") as f:
          return yaml.safe_load(f)
  ```
- **`config.yaml` is NOT cached in memory.** Every invocation of `load_config()` reads directly from the filesystem. As soon as `/v1/onboard/confirm` writes the new tenant block, subsequent calls to `load_config()` immediately reflect the changes.
- Furthermore, when a model finishes training, line 182 of [`src/api/onboarding.py`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L182) calls `clear_model_cache()`, purging `MODEL_CACHE` so any cached state is refreshed.

---

### 12. Recommendations for Untrained Tenants & Valid Customer IDs

**File:** [`src/api/recommendations.py`](file:///d:/Projects/AI_POD/src/api/recommendations.py#L138-L264), [`L340-L351`](file:///d:/Projects/AI_POD/src/api/recommendations.py#L340-L351)

#### What `GET /v1/recommendations/{customer_id}` Returns for an Untrained Tenant
Lines 249–251 of `src/api/recommendations.py`:
```python
if not is_tenant_trained(tenant_id, storage=storage):
    return _get_fallback_recommendations(tenant_id, top_n, storage=storage), True
```
- **It does NOT raise an error.** It returns HTTP 200 with `fallback: True`:
  ```json
  {
    "tenant_id": "<tenant_id>",
    "customer_id": "<customer_id>",
    "recommendations": [...],
    "fallback": true
  }
  ```
- `_get_fallback_recommendations` builds a popularity counter by inspecting:
  1. `data/processed/{tenant_id}/interactions.csv`
  2. In-memory queued tracking events (`src/api/tracking.py:get_queued_events`)
  3. Raw adapter data if configured in `config.yaml`
  4. Product metadata from `data/processed/{tenant_id}/products.csv`
- **If the tenant has no interactions anywhere:** `counter` is empty, so it returns `recommendations: []` with `fallback: true`.

#### Which Customer IDs Are Valid?
- Lines 341–342:
  ```python
  if not customer_id or not customer_id.strip():
      raise HTTPException(status_code=400, detail="customer_id cannot be blank")
  ```
- **Any non-empty string is accepted.** For untrained tenants (or unknown customers), the system catches the cold-start condition and returns popularity fallback recommendations without validating whether the customer ID exists in the database.

---

## Section E: Dashboard Data Integrity & Mock Analysis

### 13. Hardcoded, Mocked & Random Values in Dashboard Pages

#### 1. [`Overview.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/Overview.jsx)

| Item / Field | Code Location | Nature of Mock / Hardcoding | Real Backend Endpoint To Replace It |
| :--- | :--- | :--- | :--- |
| `RECENT_EVENTS` array | Lines 24–30 | Static array of 5 fake events (`7590-VHVEG` viewing `OnlineSecurity`, `2345-ABCD` purchasing `TechSupport`, etc.) | **None exists.** Tracking events are ingested via `POST /v1/track` to SQS or in-memory, but no query endpoint exists to retrieve historical events for a tenant. |
| `Requests Today` stat card | Line 78 | Hardcoded string `"1,240"` with subtitle `"+12% from yesterday"` | **None exists.** No request metrics or telemetry aggregation endpoint exists in the backend. |
| `API Keys Active` stat card | Line 79 | Hardcoded string `"2"` with subtitle `"pk + sk"` | Could be derived from `/accounts/me` or `/onboard/keys`. No dedicated count endpoint exists. |
| Model Health fallback values | Lines 99–102 | `'XGBoost Learned Ranking'`, NDCG: `0.607`, Precision: `0.316`, Last Trained: `'Today at 09:14'` | Endpoint `GET /v1/onboard/status` exists, but backend `_execute_training_job` **never saves winner_model or metrics** into the status JSON. |

#### 2. [`Analytics.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/Analytics.jsx)

| Item / Field | Code Location | Nature of Mock / Hardcoding | Real Backend Endpoint To Replace It |
| :--- | :--- | :--- | :--- |
| `DAILY` chart data | Lines 3–11 | 7-day array of Mon–Sun numbers for views, clicks, purchases, and cart additions | **None exists.** No time-series aggregation endpoint exists. |
| `TOP_PRODUCTS` chart data | Lines 13–19 | Static array of 5 Telco add-on products (`Online Security`, `Tech Support`, etc.) | **None exists.** No top-recommended products analytics endpoint exists. |
| Metric summary pills | Lines 37–40 | Hardcoded Total Events (`3,435`, `+18%`), Recommendations (`12,450`, `+24%`), CTR (`14.2%`, `+2.1%`), Fallback Rate (`3.1%`, `-0.8%`) | **None exists.** Backend lacks analytics calculation APIs. |

#### 3. [`ModelStatus.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/ModelStatus.jsx)

| Item / Field | Code Location | Nature of Mock / Hardcoding | Real Backend Endpoint To Replace It |
| :--- | :--- | :--- | :--- |
| `MODELS_DATA` array | Lines 6–11 | Static array of 4 models with hardcoded NDCG, Precision, and Recall scores | **None exists.** Backend `/onboard/train` does not run evaluation, and `/onboard/status` does not serve a model leaderboard. |
| `Last trained` timestamp | Line 53 | Static string `"Today, 09:14"` | Could be extracted from `status/{tenant_id}.json` (`updated_at`), but is hardcoded in JSX. |
| `Dataset Statistics` | Lines 96–100 | Static numbers: Customers: `7043`, Products: `10`, Interactions: `20381` (Telco numbers) | **None exists.** No endpoint returns dataset profile cardinality counts for a tenant. |

#### 4. [`ApiKeys.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/ApiKeys.jsx)

| Item / Field | Code Location | Nature of Mock / Hardcoding | Real Backend Endpoint To Replace It |
| :--- | :--- | :--- | :--- |
| `pk` and `sk` state | Lines 15–16 | Reads from `localStorage`. If absent, falls back to `'pk-live-xxxx…'` and `'sk-live-xxxx…'` | `/accounts/me` returns `public_key`. For `sk`, the backend deliberately never returns private keys after creation. If `localStorage` is cleared, `sk` displays the fallback string forever. |
| Key Permissions table | Lines 84–97 | Static JSX documentation table | Static UI documentation. Endpoint `POST /accounts/keys/regenerate` is real and functional. |

---

## Section F: Current State on Disk

### 14. Filesystem State (2-Level Tree, Sizes, Modified Dates)

*All private and public API key values and password hashes have been redacted.*

#### 1. `data/raw`
```
D:\Projects\AI_POD\data\raw
├── .gitkeep                             [0 bytes, 2026-07-25 09:30]
├── carrie_eccomerce_raw.csv             [45,580,700 bytes, 2026-09-29 00:33]
├── fixture_ecommerce.csv                [411 bytes, 2026-08-07 17:44]
├── fresh_cart_co_raw.csv                [12,499,844 bytes, 2026-10-05 13:16]
├── movielens_small.csv                  [45,319 bytes, 2026-08-08 15:43]
├── online_retail.csv                    [33,941,412 bytes, 2026-09-26 23:13]
├── online_retail_II.xlsx                [45,622,278 bytes, 2026-09-26 23:09]
├── online_retail_ii.zip                 [45,622,418 bytes, 2026-09-26 23:05]
├── saas_subscription_churn.csv          [3,331 bytes, 2026-08-13 09:45]
├── t_raw.csv                            [168 bytes, 2026-09-24 22:26]
├── telco_customer_churn.csv             [977,501 bytes, 2026-07-25 10:08]
├── thread_co_raw.csv                    [47,185,041 bytes, 2026-10-04 19:56]
├── movielens_small/                     [Directory, 2026-08-08 15:42]
│   ├── links.csv                        [197,979 bytes, 2026-08-08 15:42]
│   ├── movies.csv                       [494,431 bytes, 2026-08-08 15:42]
│   ├── ratings.csv                      [2,483,723 bytes, 2026-08-08 15:42]
│   ├── README.txt                       [8,342 bytes, 2026-08-08 15:42]
│   └── tags.csv                         [118,660 bytes, 2026-08-08 15:42]
└── sessions/                            [Directory, 2026-10-04 17:16]
    └── [13 session subdirectories from tracking tests]
```

#### 2. `data/processed`
```
D:\Projects\AI_POD\data\processed
├── .gitkeep                             [0 bytes, 2026-07-25 09:30]
├── customers.csv                        [569,464 bytes, 2026-10-10 15:16]
├── interactions.csv                     [795,027 bytes, 2026-10-10 15:16]
├── products.csv                         [418 bytes, 2026-10-10 15:16]
├── auto_demo/                           [Directory, 2026-08-13 09:48]
│   ├── customers.csv                    [3,383 bytes, 2026-08-13 09:48]
│   ├── interactions.csv                 [5,971 bytes, 2026-08-13 09:48]
│   └── products.csv                     [354 bytes, 2026-08-13 09:48]
├── fixture_ecommerce/                   [Directory, 2026-10-06 14:01]
│   ├── customers.csv                    [287 bytes, 2026-10-06 14:01]
│   ├── interactions.csv                 [319 bytes, 2026-10-06 14:01]
│   └── products.csv                     [120 bytes, 2026-10-06 14:01]
├── movielens_demo/                      [Directory, 2026-10-06 14:00]
│   ├── customers.csv                    [12,185 bytes, 2026-10-06 14:00]
│   ├── interactions.csv                 [94,290 bytes, 2026-10-06 14:00]
│   └── products.csv                     [374 bytes, 2026-10-06 14:00]
├── movielens_small/                     [Directory, 2026-08-08 15:58]
│   ├── customers.csv                    [12,185 bytes, 2026-08-08 15:58]
│   ├── interactions.csv                 [94,290 bytes, 2026-08-08 15:58]
│   └── products.csv                     [374 bytes, 2026-08-08 15:58]
├── online_retail/                       [Directory, 2026-09-26 23:25]
│   ├── customers.csv                    [90,547 bytes, 2026-09-26 23:25]
│   ├── interactions.csv                 [4,420,007 bytes, 2026-09-26 23:25]
│   └── products.csv                     [126,900 bytes, 2026-09-26 23:25]
├── telco_default/                       [Directory, 2026-10-06 14:00]
│   ├── customers.csv                    [569,464 bytes, 2026-10-06 14:00]
│   ├── interactions.csv                 [795,027 bytes, 2026-10-06 14:00]
│   └── products.csv                     [418 bytes, 2026-10-06 14:00]
└── thread_co/                           [Directory, 2026-10-05 12:42]
    ├── customers.csv                    [13,358,742 bytes, 2026-10-05 12:42]
    ├── interactions.csv                 [27,853,568 bytes, 2026-10-05 12:42]
    └── products.csv                     [475,675 bytes, 2026-10-05 12:42]
```

#### 3. `models/`
```
D:\Projects\AI_POD\models
├── .gitkeep                             [0 bytes, 2026-08-03 09:55]
├── final_model.joblib                   [1,040,135 bytes, 2026-10-10 15:16]
├── auto_demo/final_model.joblib         [126,833 bytes, 2026-10-06 14:05]
├── carrie_eccomerce/final_model.joblib  [4,969,890 bytes, 2026-10-01 10:58]
├── fixture_ecommerce/final_model.joblib [95,448 bytes, 2026-10-06 14:01]
├── fresh_cart_co/final_model.joblib     [2,311,203 bytes, 2026-10-06 14:05]
├── movielens_demo/final_model.joblib    [97,665 bytes, 2026-10-06 14:00]
├── movielens_small/final_model.joblib   [267,761 bytes, 2026-10-01 10:56]
├── online_retail/final_model.joblib     [9,996,879 bytes, 2026-10-01 10:58]
├── telco_default/final_model.joblib     [854,356 bytes, 2026-10-06 14:01]
└── thread_co/final_model.joblib         [60,124,546 bytes, 2026-10-06 14:05]
```

#### 4. `status/`
```
D:\Projects\AI_POD\status
└── .gitkeep                             [0 bytes, 2026-10-10 15:16]
```
*(No status files are currently saved on disk).*

#### 5. `config/`
```
D:\Projects\AI_POD\config
├── accounts.example.yaml                [827 bytes, 2026-10-10 15:16]
├── accounts.local.yaml                  [1,712 bytes, 2026-11-02 22:54]
├── config.yaml                          [14,537 bytes, 2026-10-10 15:16]
├── demo_saved_keys.json                 [375 bytes, 2026-10-27 10:00]
├── tenants_auth.example.yaml            [2,029 bytes, 2026-10-10 15:16]
└── tenants_auth.local.yaml              [545 bytes, 2026-11-02 22:54]
```

#### Accounts on Disk ([`config/accounts.local.yaml`](file:///d:/Projects/AI_POD/config/accounts.local.yaml))
- `acc_admin01`: `admin@gmail.com` | Tenant: `admin` | Verified: `true` | Role: `admin`
- `acc_8f2k1x`: `dev@acme.com` | Tenant: `acme_corp` | Verified: `false`
- `acc_cs8sbt`: `achinesanjana11@gmail.com` | Tenant: `sanjgrocery` | Verified: `false` | Code: `[EXPIRED]`
- `acc_0kla2f`: `achinesanjana2004@gmail.com` | Tenant: `sanjtelco` | Verified: `false` | Code: `[EXPIRED]`

#### Keys on Disk ([`config/tenants_auth.local.yaml`](file:///d:/Projects/AI_POD/config/tenants_auth.local.yaml))
- `sk-sanjgrocery-[REDACTED]`: Tenant `sanjgrocery` (private)
- `pk-sanjgrocery-[REDACTED]`: Tenant `sanjgrocery` (public)
- `sk-sanjtelco-[REDACTED]`: Tenant `sanjtelco` (private)
- `pk-sanjtelco-[REDACTED]`: Tenant `sanjtelco` (public)

---

## Root Causes Ranked by Severity

### 1. Critical Header Disconnect on Onboarding Endpoints (Severity: CRITICAL)
- **Problem:** All endpoints under [`/v1/onboard/*`](file:///d:/Projects/AI_POD/src/api/onboarding.py) (`/upload`, `/validate`, `/confirm`, `/train`, `/status`) are guarded by `tenant_id: str = Depends(get_current_tenant)`. In [`src/api/auth.py:213-228`](file:///d:/Projects/AI_POD/src/api/auth.py#L213-L228), `get_current_tenant` **only checks `X-API-Key`**. Meanwhile, [`frontend/src/api/client.js`](file:///d:/Projects/AI_POD/frontend/src/api/client.js#L38-L48) sends **only `Authorization: Bearer <token>`**.
- **Impact:** Every single onboarding network request from the frontend returns `401 Unauthorized`. To disguise this breakage, the frontend developer introduced try/catch fallbacks and timers, faking the onboarding wizard.

### 2. Disconnected Onboarding Pipeline & Training Arena Simulation (Severity: HIGH)
- **Problem:** [`src/api/onboarding.py`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L172-L178) does not run the multi-model tournament defined in [`scripts/run_pipeline.py`](file:///d:/Projects/AI_POD/scripts/run_pipeline.py#L58-L149). It only fits `LearnedRankingRecommender` and does not evaluate models or calculate NDCG@5 metrics. It never records `winner_model` or `metrics` in `status/{tenant_id}.json`.
- **Impact:** Because the backend status endpoint never returns model metrics, the frontend in [`TrainingStep.jsx:80-90`](file:///d:/Projects/AI_POD/frontend/src/pages/onboarding/TrainingStep.jsx#L80-L90) forcibly simulates completion after 12 seconds using a `setTimeout` with hardcoded numbers (`0.607`, `0.316`, `0.887`).

### 3. Missing Email Verification UI Workflow (Severity: HIGH)
- **Problem:** The backend generates 6-digit verification codes and enforces them on login when `ENFORCE_EMAIL_VERIFICATION=true`. However, the frontend has **no page, modal, or form to enter the code**, does not import `verifyEmail` or `resendVerification`, and simply navigates past verification on signup.
- **Impact:** If email verification is enforced, newly registered users who log out are permanently locked out of their accounts with no in-app recourse.

### 4. Fabricated Telemetry and Analytics in Dashboard (Severity: MEDIUM-HIGH)
- **Problem:** The entire telemetry layer in [`Analytics.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/Analytics.jsx) (`DAILY` events, `TOP_PRODUCTS`, CTR, fallback rate), [`ModelStatus.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/ModelStatus.jsx) (`MODELS_DATA` metrics), and [`Overview.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/Overview.jsx) (`RECENT_EVENTS`, `Requests Today`) consists of hardcoded constants.
- **Impact:** No live behavioral tracking or performance metrics from `/v1/track` are reflected in the tenant dashboard. Operators are shown static mock data.

### 5. Non-Atomic Configuration & Key File Persistence (Severity: MEDIUM)
- **Problem:** Both [`src/utils/key_manager.py:143`](file:///d:/Projects/AI_POD/src/utils/key_manager.py#L143) and [`src/accounts/storage.py`](file:///d:/Projects/AI_POD/src/accounts/storage.py) open local YAML files in `"w"` mode and dump content directly without writing to a temp file and performing an atomic rename.
- **Impact:** Concurrent API requests or container termination during key generation will truncate and corrupt `config/tenants_auth.local.yaml` or `config/accounts.local.yaml`.

### 6. Production Rejection of Fallback Key Suffixes (Severity: MEDIUM)
- **Problem:** In [`src/accounts/service.py:671`](file:///d:/Projects/AI_POD/src/accounts/service.py#L671), if an account's public key cannot be retrieved, it defaults to `f"pk-{tenant_id}-xxxx"`. In [`src/api/auth.py:101`](file:///d:/Projects/AI_POD/src/api/auth.py#L101), any key ending in `"-xxxx"` is unconditionally rejected in production.
- **Impact:** Any transient lookup failure in production converts into a hard 401 Unauthorized lockout.

---

## Files Requiring Review & Remediation

1. [`src/api/auth.py`](file:///d:/Projects/AI_POD/src/api/auth.py#L213-L248): Update `get_current_tenant` to accept and decode `Authorization: Bearer <session_jwt>` in addition to `X-API-Key`, or add an authentication dependency that accepts both.
2. [`frontend/src/api/client.js`](file:///d:/Projects/AI_POD/frontend/src/api/client.js#L38-L48): Update onboarding calls to pass `X-API-Key` or ensure the backend accepts Bearer session tokens. Fix `resendVerification` payload structure.
3. [`src/api/onboarding.py`](file:///d:/Projects/AI_POD/src/api/onboarding.py#L101-L190): Refactor `_execute_training_job` to run the true 4-model evaluation tournament from `scripts/run_pipeline.py`, and save `winner_model` and `metrics` into `status/{tenant_id}.json`.
4. [`frontend/src/pages/onboarding/TrainingStep.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/onboarding/TrainingStep.jsx): Remove fake `setInterval` and the 12-second forced completion `setTimeout`. Bind UI directly to real status returned from `/v1/onboard/status`.
5. [`frontend/src/pages/onboarding/IntegrateStep.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/onboarding/IntegrateStep.jsx): Remove mock recommendation fallback in the `catch` block; surface actual backend error messages to the user.
6. [`frontend/src/App.jsx`](file:///d:/Projects/AI_POD/frontend/src/App.jsx) & [`frontend/src/pages/SignUp.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/SignUp.jsx): Introduce an email verification step/page after signup before proceeding to onboarding.
7. [`frontend/src/pages/SignIn.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/SignIn.jsx): Handle HTTP 403 responses by displaying a 6-digit code entry form and a "Resend Code" button linked to `verifyEmail` and `resendVerification`.
8. [`frontend/src/pages/dashboard/Overview.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/Overview.jsx), [`Analytics.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/Analytics.jsx), [`ModelStatus.jsx`](file:///d:/Projects/AI_POD/frontend/src/pages/dashboard/ModelStatus.jsx): Replace hardcoded arrays and constants with real backend analytics endpoints or explicit empty/loading states when telemetry is unconfigured.
9. [`src/utils/key_manager.py`](file:///d:/Projects/AI_POD/src/utils/key_manager.py#L143-L145): Implement atomic file writing (`tempfile` + `os.replace`) when persisting `config/tenants_auth.local.yaml`.
10. [`src/accounts/storage.py`](file:///d:/Projects/AI_POD/src/accounts/storage.py): Implement atomic file writing when persisting `config/accounts.local.yaml`.

---
*End of Diagnostic Audit Report.*

