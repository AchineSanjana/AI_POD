# AWS Redeployment Guide: AI-POD (Auth Hardening & Modern Frontend)

**Document Version:** 3.0  
**Target Release:** Authentication Hardening + Modern React SPA Frontend  
**AWS Region:** `ap-south-1` (Mumbai)  
**Target Service:** AWS EC2 (Docker Container) + AWS ECR + Amazon S3 + AWS Systems Manager (SSM)  
**Status:** Ready for Deployment  

---

## 1. Executive Summary & Change Matrix

This runbook guides you through rebuilding and redeploying the **AI-POD** container on your existing AWS EC2 instance following the **Authentication Hardening** and **Modern Frontend Update**.

### What Changed in this Release

| Component | Previous State (`v2-auth-ratelimit`) | New State (`v3-auth-frontend`) |
| :--- | :--- | :--- |
| **Frontend Architecture** | Static HTML demo templates (`demo/onboarding.html`, `demo/telco_portal.html`) | Modern responsive **React 19 + Vite** Single Page Application (SPA) with onboarding wizard (`/onboarding/*`), protected dashboard (`/dashboard/*`), Landing, Features, and How It Works pages. |
| **Frontend Asset Delivery** | Direct file responses from `demo/` directory | Compiled static bundle (`frontend/dist/`) mounted at `/assets` and served via FastAPI SPA routes. |
| **Email Verification** | Immediate unverified account activation | Cryptographic 6-digit verification code with 15-minute expiration, email dispatch (SMTP/SES or logger), and verification gate (`/v1/accounts/verify-email`). |
| **Multi-Factor Auth (MFA)** | Single-factor password authentication | **RFC 6238 TOTP 2FA** pairing (Google Authenticator, Authy, 1Password) with 8 single-use hashed backup recovery codes (`/v1/accounts/mfa/*`). |
| **Account Lockout Defense** | IP-level rate limiting only | Account-level defense: **5 consecutive failed password attempts locks the account for 15 minutes**, preventing distributed botnet brute-forcing. |
| **Production Key Isolation** | Wildcard keys (`sk-*-xxxx`) allowed everywhere | Setting `ENV=production` strictly rejects any wildcard test keys with `401 Unauthorized`. |
| **Accounts Storage on AWS** | Local YAML file only (`config/accounts.local.yaml`) | Dual-backend: Persists to **AWS SSM Parameter Store** (`/ai_pod/accounts` as `SecureString`) or **AWS Secrets Manager** when running on AWS with `STORAGE_BACKEND=s3`. |
| **Python Dependencies** | Standard FastAPI + ML packages | Added `bcrypt>=4.0` (password hashing) and `PyJWT>=2.8` (session tokens & MFA tickets) in `requirements-prod.txt`. |

---

## 2. Registry & Deployment Parameters

Keep these configuration parameters handy throughout the redeployment process:

| Parameter | Value | Description |
| :--- | :--- | :--- |
| **AWS Account ID** | `772325758824` | Target AWS Account |
| **AWS Region** | `ap-south-1` | Mumbai Region |
| **ECR Repository** | `ai-pod-api` | Amazon Elastic Container Registry |
| **ECR Image URI** | `772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api` | Full image repository path |
| **New Image Tag** | `:latest`, `:v3-auth-frontend` | Deployment tags |
| **Rollback Image Tag** | `:v2-auth-ratelimit` | Previous stable image tag |
| **S3 Storage Bucket** | `ai-pod-storage-772325758824` | Multi-tenant model artifacts and data |
| **SSM Tenants Auth Param** | `/ai_pod/tenants_auth` | Tenant API key metadata |
| **SSM Accounts Param** | `/ai_pod/accounts` | Encrypted company account records & credentials |
| **Container Port** | `8000` | Internal FastAPI service port |
| **Host Port** | `8000` | Exposed EC2 public port (or mapped to port 80/443 via reverse proxy) |

---

## 3. Pre-Flight Codebase Checks & Wiring

Before building the Docker image, ensure these crucial files are correctly configured in your local workspace.

### 3.1. Frontend API Base URL Configuration (`frontend/src/api/client.js`)

By default, development configurations may point to `http://localhost:8000/v1`. For AWS deployment, the client browser must call relative path `/v1` (or your public EC2 DNS/IP):

```javascript
// frontend/src/api/client.js (Line 1)
const BASE_URL = import.meta.env.VITE_API_URL || '/v1';
```

> **Why this matters:** If `http://localhost:8000/v1` is hardcoded at build time, a user opening the application in their browser on AWS will have their browser attempt to contact their own local machine instead of the EC2 backend!

In `frontend/src/pages/dashboard/DashboardLayout.jsx` (around line 70), also ensure the API documentation link uses a relative path:
```jsx
// Change: href="http://localhost:8000/docs"
// To:
<a href="/docs" target="_blank" rel="noreferrer" ...>
  <ExternalLink size={15}/> API Docs
</a>
```

### 3.2. FastAPI SPA Routing Support (`src/api/app.py`)

Ensure `src/api/app.py` serves the compiled `frontend/dist/index.html` for all React SPA routes so client-side navigation and page refreshes (e.g. hitting F5 on `/dashboard` or `/onboarding/upload`) do not return `404 Not Found`:

```python
# In src/api/app.py:

# 1. Mount static frontend assets
frontend_dist_assets = PROJECT_ROOT / "frontend" / "dist" / "assets"
if frontend_dist_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist_assets)), name="frontend-assets")

# 2. SPA Route Handlers
@app.get("/", response_class=HTMLResponse)
@app.get("/features", response_class=HTMLResponse)
@app.get("/how-it-works", response_class=HTMLResponse)
@app.get("/signup", response_class=HTMLResponse)
@app.get("/signin", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/{full_path:path}", response_class=HTMLResponse)
@app.get("/onboarding", response_class=HTMLResponse)
@app.get("/onboarding/{full_path:path}", response_class=HTMLResponse)
def ui_root():
    frontend_dist_index = PROJECT_ROOT / "frontend" / "dist" / "index.html"
    if frontend_dist_index.exists():
        return FileResponse(frontend_dist_index)
    return HTMLResponse(build_home_page())
```

### 3.3. Verify `Dockerfile` Includes the Frontend

The original `Dockerfile` only copied `src`, `config`, `scripts`, `static`, and `demo`. It **must** include `frontend/dist`:

```dockerfile
# Dockerfile snippet:
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY static/ ./static/
COPY demo/ ./demo/
# Include pre-built React frontend:
COPY frontend/dist/ ./frontend/dist/
```

*(Alternatively, use the Multi-Stage Dockerfile detailed in Section 5 below to automatically compile the frontend inside Docker.)*

---

## 4. AWS Cloud Infrastructure Prerequisites

### 4.1. EC2 IAM Role Permissions for SSM Parameter Store

The EC2 instance uses an attached IAM Instance Profile (e.g., `ai-pod-ec2-role`). Because auth hardening introduces persistent account storage in **AWS Systems Manager (SSM) Parameter Store**, the EC2 role must have permissions to read and update `/ai_pod/accounts`.

Attach or verify the following policy on the EC2 IAM role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3BucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::ai-pod-storage-772325758824",
        "arn:aws:s3:::ai-pod-storage-772325758824/*"
      ]
    },
    {
      "Sid": "AllowSSMParameterAccess",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath",
        "ssm:PutParameter"
      ],
      "Resource": [
        "arn:aws:ssm:ap-south-1:772325758824:parameter/ai_pod/*"
      ]
    }
  ]
}
```

### 4.2. Initialize the Accounts Parameter in SSM

Before starting the container, create the `/ai_pod/accounts` parameter if it does not yet exist. Run this once from your local workstation using the AWS CLI:

```bash
aws ssm put-parameter \
  --name "/ai_pod/accounts" \
  --value "{\"accounts\": {}}" \
  --type "SecureString" \
  --description "AI_POD company account records and credential hashes" \
  --region ap-south-1 \
  --overwrite
```

Verify that both parameters exist:
```bash
aws ssm get-parameter --name "/ai_pod/tenants_auth" --region ap-south-1 --with-decryption
aws ssm get-parameter --name "/ai_pod/accounts" --region ap-south-1 --with-decryption
```

---

## 5. Rebuild & Push Container Image to ECR

Execute these steps from your local development workstation or build runner.

### Step 5.1: Compile the Frontend Bundle Locally

Ensure your dependencies are installed and build the optimized production distribution:

```bash
cd frontend
npm install
npm run build
cd ..
```

Confirm that the output directory exists:
- Windows (PowerShell): `Test-Path frontend/dist/index.html`
- Linux/macOS: `ls -la frontend/dist/index.html`

### Step 5.2: Authenticate Docker with Amazon ECR

Log in to the Mumbai ECR registry:

```bash
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin 772325758824.dkr.ecr.ap-south-1.amazonaws.com
```

### Step 5.3: Build the Docker Image

Build the container image with the updated backend dependencies (`bcrypt`, `PyJWT`) and the newly bundled frontend assets:

```bash
docker build \
  --platform linux/amd64 \
  -t ai-pod-api:latest \
  -t 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:latest \
  -t 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:v3-auth-frontend \
  .
```

> **Note on `--platform linux/amd64`:** If you are building on an Apple Silicon (M1/M2/M3) or ARM machine, always specify `--platform linux/amd64` to match the target EC2 x86_64 architecture.

*(Optional Alternative: Multi-Stage Dockerfile)*  
If you prefer Docker to build the frontend without requiring Node installed on your runner, use this multi-stage setup in your `Dockerfile`:

```dockerfile
# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API_URL=/v1
RUN npm run build

# Stage 2: Final Python Image
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements-prod.txt requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements-prod.txt
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY static/ ./static/
COPY demo/ ./demo/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 5.4: Push the Image to ECR

Push both the `:latest` and the immutable release tag `:v3-auth-frontend`:

```bash
docker push 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:latest
docker push 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:v3-auth-frontend
```

---

## 6. Execute Redeployment on the AWS EC2 Instance

Connect to your EC2 instance via SSH and update the running container.

### Step 6.1: Connect to EC2 Host

```bash
ssh -i /path/to/your-key.pem ubuntu@<EC2_PUBLIC_IP_OR_DNS>
```

### Step 6.2: Authenticate Docker on the EC2 Host

```bash
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin 772325758824.dkr.ecr.ap-south-1.amazonaws.com
```

### Step 6.3: Pull the Upgraded Container Image

```bash
docker pull 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:latest
```

### Step 6.4: Gracefully Stop & Remove Existing Container

```bash
docker stop ai-pod-api
docker rm ai-pod-api
```

### Step 6.5: Run the Upgraded Container with New Environment Variables

Launch the container with all required authentication, storage, and production variables configured:

```bash
docker run -d \
  --name ai-pod-api \
  --restart unless-stopped \
  -p 8000:8000 \
  -e ENV=production \
  -e AI_POD_ENV=production \
  -e STORAGE_BACKEND=s3 \
  -e STORAGE_S3_BUCKET=ai-pod-storage-772325758824 \
  -e AWS_DEFAULT_REGION=ap-south-1 \
  -e AWS_REGION=ap-south-1 \
  -e TENANTS_AUTH_PARAM_NAME=/ai_pod/tenants_auth \
  -e ACCOUNTS_SSM_PARAM=/ai_pod/accounts \
  -e JWT_SECRET_KEY="replace_with_a_secure_random_32_character_string_here!" \
  -e ENFORCE_EMAIL_VERIFICATION=false \
  772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:latest
```

### Environment Variable Guide

| Variable | Recommended Value | Purpose |
| :--- | :--- | :--- |
| `ENV` / `AI_POD_ENV` | `production` | **Crucial:** Blocks wildcard `sk-*-xxxx` keys in production. |
| `STORAGE_BACKEND` | `s3` | Tells storage modules to use S3 & AWS SSM Parameter Store. |
| `STORAGE_S3_BUCKET` | `ai-pod-storage-772325758824` | Target bucket for model artifacts. |
| `AWS_DEFAULT_REGION` | `ap-south-1` | AWS region for Boto3 clients. |
| `TENANTS_AUTH_PARAM_NAME`| `/ai_pod/tenants_auth` | SSM Parameter for tenant API keys. |
| `ACCOUNTS_SSM_PARAM` | `/ai_pod/accounts` | SSM Parameter for persistent company accounts. |
| `JWT_SECRET_KEY` | *(Random 32+ char string)* | HMAC secret key for signing session tokens and MFA tickets. |
| `ENFORCE_EMAIL_VERIFICATION` | `false` or `true` | If `true`, accounts cannot log in until their email is verified. |

#### Optional: Real Email Dispatch (Amazon SES / SMTP)
If you wish to send real 6-digit verification codes to user inboxes instead of logging them to container console:
```bash
  -e SMTP_HOST="email-smtp.ap-south-1.amazonaws.com" \
  -e SMTP_PORT="587" \
  -e SMTP_USER="<YOUR_SES_SMTP_USERNAME>" \
  -e SMTP_PASS="<YOUR_SES_SMTP_PASSWORD>" \
  -e SMTP_FROM="noreply@yourverifieddomain.com" \
```

---

## 7. Post-Deployment Verification & Smoke Tests

Run these tests directly on the EC2 host (or from an external terminal pointing to your EC2 IP) to verify that both the modern frontend and hardened authentication are operational.

### 7.1. Check Container Health & Logs

```bash
docker ps --filter "name=ai-pod-api"
docker logs ai-pod-api --tail 50
```

Verify that the healthcheck returns `200 OK`:
```bash
curl -i http://localhost:8000/health
```
**Expected Response:**
```json
HTTP/1.1 200 OK
{"status": "ok"}
```

### 7.2. Verify Frontend Delivery

Check that FastAPI delivers the React Vite application at the root and deep routes:
```bash
curl -s http://localhost:8000/ | grep -i "vite"
curl -s http://localhost:8000/features | grep -i "vite"
curl -s http://localhost:8000/dashboard | grep -i "vite"
```
**Expected Result:** Returns HTML containing `<script type="module" src="/assets/index-....js"></script>`.

Now open `http://<EC2_PUBLIC_IP>:8000/` in your web browser:
1. Verify the modern dark-themed Landing page loads.
2. Click **Features** and **How It Works** in the navbar to confirm client-side routing.
3. Refresh the page (F5) to ensure FastAPI returns the index file without 404 errors.

---

### 7.3. Test Hardened Authentication Flow

#### Step 1: Sign up a new company account
```bash
curl -i -X POST http://localhost:8000/v1/accounts/signup \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "Acme Cloud",
    "email": "admin@acmecloud.io",
    "password": "SecurePassword123!"
  }'
```
**Expected Response:** `HTTP/1.1 201 Created`
```json
{
  "account_id": "acc_xxxxxx",
  "tenant_id": "acme_cloud",
  "company_name": "Acme Cloud",
  "email": "admin@acmecloud.io",
  "email_verified": false,
  "verification_sent": true,
  "private_key": "sk-acme_cloud-...",
  "public_key": "pk-acme_cloud-..."
}
```

#### Step 2: Retrieve the verification code from container logs
If SMTP was not configured, retrieve the verification code from the logs:
```bash
docker logs ai-pod-api --tail 20 | grep "Verification code for 'Acme Cloud'"
```

#### Step 3: Verify the account email
```bash
curl -i -X POST http://localhost:8000/v1/accounts/verify-email \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@acmecloud.io",
    "code": "<6-DIGIT-CODE>"
  }'
```
**Expected Response:** `HTTP/1.1 200 OK` (`email_verified: true`).

#### Step 4: Log in and obtain a JWT Session Token
```bash
curl -i -X POST http://localhost:8000/v1/accounts/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@acmecloud.io",
    "password": "SecurePassword123!"
  }'
```
**Expected Response:** `HTTP/1.1 200 OK` with session `token`. Save this token as `$TOKEN`.

#### Step 5: Test MFA Setup (2FA)
Initiate TOTP setup using the Bearer token:
```bash
curl -i -X POST http://localhost:8000/v1/accounts/mfa/setup \
  -H "Authorization: Bearer $TOKEN"
```
**Expected Response:** Returns `totp_secret` and `otpauth_uri`.

---

### 7.4. Verify Production Key Isolation (Negative Security Test)

Confirm that mock wildcard keys (`-xxxx`) are strictly blocked in production:
```bash
curl -i -H "X-API-Key: sk-telco-xxxx" \
  "http://localhost:8000/v1/recommendations?customer_id=7590-VHVEG&top_n=5"
```
**Expected Response:** `HTTP/1.1 401 Unauthorized`
```json
{
  "detail": "Invalid API key or unknown tenant. Ensure you provide a valid X-API-Key header."
}
```

### 7.5. Verify Live Recommendations with a Real Private Key

Use the legitimate API key configured in `/ai_pod/tenants_auth`:
```bash
curl -i -H "X-API-Key: <VALID_PRODUCTION_KEY>" \
  "http://localhost:8000/v1/recommendations?customer_id=7590-VHVEG&top_n=5"
```
**Expected Response:** `HTTP/1.1 200 OK` with ranked recommendation results.

---

## 8. Rollback Procedure (Disaster Recovery)

If any critical issue arises during deployment, you can instantly roll back to the previously verified image tag `:v2-auth-ratelimit`:

```bash
# 1. Stop and remove the broken container
docker stop ai-pod-api && docker rm ai-pod-api

# 2. Relaunch the previous stable image
docker run -d \
  --name ai-pod-api \
  --restart unless-stopped \
  -p 8000:8000 \
  -e STORAGE_BACKEND=s3 \
  -e STORAGE_S3_BUCKET=ai-pod-storage-772325758824 \
  -e AWS_DEFAULT_REGION=ap-south-1 \
  -e TENANTS_AUTH_PARAM_NAME=/ai_pod/tenants_auth \
  772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:v2-auth-ratelimit

# 3. Verify health
curl -i http://localhost:8000/health
```

---

## 9. Troubleshooting & FAQ

### Issue 1: Frontend fails to make requests with `Failed to fetch` or `ERR_CONNECTION_REFUSED`
* **Root Cause:** The frontend was built with `VITE_API_URL` set to `http://localhost:8000/v1`, causing the client's web browser to send requests to its own machine.
* **Fix:** In `frontend/src/api/client.js`, ensure `BASE_URL` defaults to `/v1` (relative path) or pass `VITE_API_URL=/v1 npm run build` before packaging the container.

### Issue 2: Refreshing `/dashboard` or `/onboarding` returns `404 Not Found`
* **Root Cause:** FastAPI route table does not have an explicit route for SPA subpaths, so the web server looks for an API route instead of delegating to `index.html`.
* **Fix:** Verify `src/api/app.py` has `@app.get("/dashboard/{full_path:path}")` and `@app.get("/onboarding/{full_path:path}")` returning `FileResponse(frontend_dist_index)`.

### Issue 3: Container logs show `botocore.exceptions.ClientError: AccessDeniedException` on SSM
* **Root Cause:** The EC2 IAM Instance Profile lacks `ssm:PutParameter` or `ssm:GetParameter` for `/ai_pod/*`.
* **Fix:** Add the policy in Section 4.1 to the EC2 IAM role in the AWS IAM Console.

### Issue 4: Account gets locked with `HTTP 423 Locked`
* **Root Cause:** 5 consecutive failed login attempts trigger the 15-minute brute-force lockout defense.
* **Fix:** Wait 15 minutes for the lockout window to expire, or update the parameter in SSM / local store to reset `failed_login_attempts: 0` and clear `locked_until`.

---

## 10. Summary Checklist

- [ ] Frontend compiled locally (`npm run build`) and `frontend/dist/index.html` exists.
- [ ] `frontend/src/api/client.js` verified using relative path `/v1`.
- [ ] SPA catch-all routes added to `src/api/app.py`.
- [ ] `Dockerfile` updated to copy `frontend/dist/`.
- [ ] SSM parameter `/ai_pod/accounts` created as `SecureString`.
- [ ] EC2 IAM Role granted SSM read/write permissions.
- [ ] Container image built with `--platform linux/amd64` and pushed to ECR with `:v3-auth-frontend`.
- [ ] Container running on EC2 with `ENV=production` and `ACCOUNTS_SSM_PARAM=/ai_pod/accounts`.
- [ ] Healthcheck (`/health`) and Landing Page (`/`) verified.
- [ ] Account signup, email verification, and TOTP MFA smoke-tested.

