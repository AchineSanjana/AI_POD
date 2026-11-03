# Frontend Email Verification Flow Hardening & Fixes

## 1. Overview
This update resolves the authentication token pollution bug, implements the complete 6-digit email verification page and flow, fixes redirection and resend behavior on `403 Forbidden (email not verified)` and `423 Locked`, eliminates hardcoded email checks, isolates session JWT tokens from tenant API keys, and mounts unverified alert banners in application layouts.

---

## 2. Files Changed & Created

| File | Change Type | Purpose |
| :--- | :--- | :--- |
| `frontend/src/api/client.js` | Modified | Updated `resendVerification({ email })` and `verifyEmail({ email, code })` parameter signatures to match backend contracts; added session and API key helpers (`getSessionToken`, `clearSessionToken`, `getStoredKeys`, `clearAllTokens`). |
| `frontend/src/pages/VerifyEmail.jsx` | **Created** | Dedicated verification page at `/verify-email`. Supports email detection (router state or `?email=`), 6-digit numeric input with paste stripping and auto-focus, Verify button, Resend button with a 60-second cooldown timer, error banners for 400/429/network errors, and redirect to `/signin` with prefilled email on success. |
| `frontend/src/App.jsx` | Modified | Registered public route `<Route path="/verify-email" element={<VerifyEmail />} />`. |
| `frontend/src/pages/SignUp.jsx` | Modified | **Bug fix**: Removed illegal `authLogin(data.private_key, ...)` which previously stored the `sk-` private key as a session JWT. It now persists only `aipod_pk` and `aipod_sk` to `localStorage` (so `IntegrateStep` can display them once) and navigates to `/verify-email` with `{ state: { email: form.email } }`. |
| `frontend/src/pages/SignIn.jsx` | Modified | On `403` unverified error: automatically dispatches `resendVerification({ email })` and redirects to `/verify-email`. On `423` account locked: displays security lockout message. Replaced hardcoded `admin@gmail.com` check with `Boolean(me?.is_admin || me?.role === 'admin')` from backend profile. Supports prefilled email and success banners from router state or query params. |
| `frontend/src/context/AuthContext.jsx` | Modified | Confirmed `aipod_token` is exclusively a session JWT. On initialization, if `getMe()` fails with `401 Unauthorized`, clears only `aipod_token` while leaving `aipod_pk` / `aipod_sk` intact. |
| `frontend/src/components/UnverifiedBanner.jsx` | **Created** | Warning alert banner displayed when `user.email_verified === false`, featuring a link to `/verify-email` with prefilled email state. |
| `frontend/src/pages/dashboard/DashboardLayout.jsx` | Modified | Rendered `<UnverifiedBanner />` above main content outlet; moved `Sidebar` out of render tree to resolve React compiler lifecycle warning. |
| `frontend/src/pages/onboarding/OnboardingLayout.jsx` | Modified | Rendered `<UnverifiedBanner />` above onboarding wizard content outlet; cleaned up unused imports. |

---

## 3. Route Table

| Route | Component | Access | Description |
| :--- | :--- | :--- | :--- |
| `/` | `Landing` | Public | Landing page |
| `/features` | `Features` | Public | Product features |
| `/how-it-works` | `HowItWorks` | Public | Technical architecture & process |
| `/signup` | `SignUp` | Public | Account registration (persists `aipod_pk`/`aipod_sk`, redirects to `/verify-email`) |
| `/signin` | `SignIn` | Public | Authentication with TOTP 2FA, 403 auto-resend redirect, and 423 lockout alerts |
| `/verify-email` | `VerifyEmail` | **Public** | 6-digit verification code entry, paste support, and 60s resend cooldown |
| `/onboarding/*` | `OnboardingLayout` | Hybrid / Protected | 5-step onboarding wizard with unverified email warning banner |
| `/dashboard/*` | `DashboardLayout` | **Protected** | Main tenant dashboard with unverified email warning banner |

---

## 4. Verification & Build Results

### Oxlint
```
$ npm run lint
Found 27 warnings (pre-existing in unrelated demo pages) and 0 errors.
Finished in 90ms on 28 files with 104 rules.
```

### Vite Production Build
```
$ npm run build
vite v8.3.5 building client environment for production...
transforming...
✓ 2636 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.91 kB │ gzip:   0.48 kB
dist/assets/index-DzKvr4YD.css    8.36 kB │ gzip:   2.65 kB
dist/assets/index-B9oahLRm.js   794.07 kB │ gzip: 227.61 kB
✓ built in 2.24s
```

### Backend Auth & Hardening Pytest Suite
```
$ pytest tests/test_accounts.py tests/test_auth_hardening.py
============================= 27 passed in 10.37s =============================
```

---

## 5. Manual Verification Test Script

### Step 1: Sign Up Flow
1. Navigate to `http://localhost:5173/signup`.
2. Fill in:
   - Company Name: `Acme Retail`
   - Work Email: `testuser@example.com`
   - Password: `Password123!`
   - Confirm Password: `Password123!`
3. Click **Create Account**.
4. **Verify**:
   - User is redirected to `/verify-email`.
   - In browser DevTools > Application > Local Storage:
     - `aipod_pk` contains `pk-...`
     - `aipod_sk` contains `sk-...`
     - `aipod_token` is **not set** (no fake JWT token pollution).
   - The email `testuser@example.com` is displayed on the verification card.

### Step 2: Code Entry & Paste Support
1. On `/verify-email`:
   - Verify that the 6-digit input is auto-focused.
   - Type non-numeric characters (e.g., `abc`); verify they are stripped.
   - Copy a 6-digit code like `123456` or `123-456` to clipboard and press `Ctrl+V` (paste).
   - Verify non-digit characters are stripped and exactly `123456` is populated.
2. Submit an incorrect code `000000`:
   - Verify error banner appears: `"Invalid or expired verification code..."`.

### Step 3: Resend Button & 60s Cooldown
1. Click **Resend verification code**.
   - Verify the button transitions to disabled state with countdown: `"Resend code in 59s"`.
   - Verify consecutive clicks are blocked while the cooldown ticks down.
   - If backend rate limit returns `429`, verify error alert displays the retry advisory.

### Step 4: Successful Email Verification & Prefilled Sign In
1. In dev mode, fetch the code dispatched to `testuser@example.com`:
   - Run `GET /v1/accounts/dev/last-verification?email=testuser@example.com`.
2. Enter the retrieved 6-digit code into the input on `/verify-email` and click **Verify Email**.
3. **Verify**:
   - Green success banner is displayed: `"Email verified successfully! Redirecting to sign in..."`.
   - User is redirected to `/signin`.
   - The Email input is prefilled with `testuser@example.com`.
   - A success alert is displayed: `"Email verified successfully. Please sign in to continue."`.

### Step 5: Sign In with Unverified Account (403 Auto-Resend)
1. In the database / backend state, create or use an account where `email_verified=False`.
2. Attempt to sign in on `/signin` with valid credentials for that unverified account.
3. **Verify**:
   - Backend returns `403 Forbidden`.
   - Frontend triggers `resendVerification({ email })` automatically in the background.
   - User is automatically redirected to `/verify-email`.
   - Router state delivers `autoResent: true`, triggering the 60-second cooldown timer immediately and displaying: `"Your email address is not verified yet. We just sent a verification code to your inbox."`.

### Step 6: Account Lockout (423 Locked)
1. On `/signin`, submit 5 consecutive incorrect passwords for an account.
2. **Verify**:
   - Backend returns `423 Locked`.
   - Frontend renders the alert: `"Account temporarily locked due to consecutive failed attempts. Please try again later."`.
   - User is not redirected.

### Step 7: Unverified Banner in Dashboard & Onboarding
1. Sign in with an account having `email_verified: false` (if permitted in dev or bypass mode).
2. Navigate to `/dashboard` or `/onboarding/upload`.
3. **Verify**:
   - Amber warning banner appears above page content: `"Your email (...) is not verified. Please verify your email to secure your account."`.
   - Clicking **Verify Email** navigates to `/verify-email` with the user's email prefilled.

