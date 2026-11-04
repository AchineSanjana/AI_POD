# AI_POD EC2 Production Deployment Checklist

**Pragmatic, Step-by-Step Operations Manual for AWS EC2 Deployment**  
*Document Version: 1.0 | Date: November 2026*  
*Target Infrastructure: AWS EC2 (Ubuntu 22.04 LTS / Amazon Linux 2023), S3, SES, SQS (Optional)*

---

## Pre-Flight Status Legend
- **`[VERIFIED LOCALLY]`**: Tested and proven end-to-end in the AI_POD repository test suite and smoke test.
- **`[NOT YET VERIFIED ON AWS]`**: Infrastructure configuration specified and tested with mocked services (e.g. `moto`), but requires live verification on active AWS cloud infrastructure.

---

## 1. Environment Variables Reference

Every environment variable must be configured in production (e.g., via `/etc/environment`, systemd unit environment, or AWS Secrets Manager).

| Variable Name | Required? | Format / Example | Where to Obtain / Notes | Failure Impact if Missing |
| :--- | :--- | :--- | :--- | :--- |
| `ENV` or `AI_POD_ENV` | **YES** | `production` | Set manually in server environment. | Test key backdoors (`sk-*-xxxx`) remain enabled; dev endpoints like `/dev/last-verification` are exposed. |
| `JWT_SECRET_KEY` | **YES** | `64+ char random hex` (`openssl rand -hex 32`) | Generate cryptographically via openssl. | Server logs security warning; uses insecure fallback; session JWTs vulnerable to forgery. |
| `STORAGE_BACKEND` | **YES** | `s3` (or `local` for single-node) | Set to `s3` for multi-worker EC2 deployment. | Defaults to local disk storage; breaks file sharing across multiple uvicorn workers. |
| `S3_BUCKET` | **YES** (if S3) | `my-aipod-production-data` | Created in AWS S3 Console in the target region. | S3 storage backend fails initialization with `ValueError`. |
| `AWS_DEFAULT_REGION` | **YES** (if S3) | `us-east-1` (or your target region) | Your AWS deployment region. | Boto3 fails to resolve AWS service endpoints. |
| `SMTP_HOST` | **YES** (in Prod) | `email-smtp.us-east-1.amazonaws.com` | AWS SES SMTP Settings in AWS Console. | Server logs error on startup; verification emails printed to server console instead of delivered. |
| `SMTP_PORT` | **YES** (in Prod) | `587` | AWS SES SMTP standard TLS port. | SMTP connection fails. |
| `SMTP_USER` | **YES** (in Prod) | `AKIA...` (SES SMTP User) | Generated in AWS SES SMTP Credentials. | SMTP authentication fails. |
| `SMTP_PASS` | **YES** (in Prod) | Secret SMTP password | Generated in AWS SES SMTP Credentials. | SMTP authentication fails. |
| `SMTP_FROM` | **YES** (in Prod) | `noreply@yourdomain.com` | Verified domain or email address in SES. | SES rejects outgoing emails with `MessageRejected`. |
| `ENFORCE_EMAIL_VERIFICATION` | Optional | `true` | Defaults to `true` in production. | If false, users can log in before proving email ownership. |
| `SQS_QUEUE_URL` | Optional | `https://sqs.us-east-1.amazonaws.com/...` | AWS SQS Console (if using SQS queue for events). | Tracking falls back to local in-process queue / batch flusher. |
| `CORS_ORIGINS` | Recommended | `https://app.yourdomain.com,https://store.yourdomain.com` | Comma-separated domains allowed to call the API. | Defaults to `*` (wildcard CORS). |

---

## 2. Recommended EC2 Instance & Uvicorn Command

### 2.1 Instance Sizing
- **Recommended**: `t3.large` or `c6i.large` (2 vCPUs, 4-8 GB RAM minimum for training XGBoost and TruncatedSVD models).
- **Disk**: 40 GB+ gp3 EBS volume.

### 2.2 Systemd Unit File (`/etc/systemd/system/aipod.service`)
```ini
[Unit]
Description=AI_POD FastAPI Recommendation Service
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/aipod
EnvironmentFile=/etc/aipod.env
ExecStart=/opt/aipod/venv/bin/uvicorn src.api.app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --lifespan on \
    --proxy-headers \
    --forwarded-allow-ips "*"

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> [!IMPORTANT]
> When running multiple workers (`--workers 4`), you **MUST** configure `STORAGE_BACKEND=s3` so that dataset uploads, trained models, status files, and telemetry logs are shared uniformly across worker processes.

---

## 3. S3 Bucket & IAM Permissions

### 3.1 S3 Bucket Setup
Create an S3 bucket with versioning and SSE-S3 encryption enabled:
```bash
aws s3api create-bucket --bucket my-aipod-production-data --region us-east-1
aws s3api put-bucket-encryption --bucket my-aipod-production-data \
    --server-side-encryption-configuration '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}'
```

### 3.2 IAM Role for EC2 Instance (`AI_POD_EC2_Role`)
Attach this IAM policy to the EC2 instance profile:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AIPODS3StorageAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-aipod-production-data",
        "arn:aws:s3:::my-aipod-production-data/*"
      ]
    },
    {
      "Sid": "AIPODSESEmailDispatch",
      "Effect": "Allow",
      "Action": [
        "ses:SendEmail",
        "ses:SendRawEmail"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## 4. Amazon SES Setup for Transactional Emails

1. **Verify Sending Domain**: In Amazon SES Console, verify your production domain (e.g., `yourdomain.com`) with DKIM DNS records.
2. **Move Out of SES Sandbox**: By default, SES accounts are in a sandbox where emails can only be sent to verified addresses. Submit an SES Production Access request in the AWS Console.
3. **Generate SMTP Credentials**: In AWS SES -> SMTP Settings -> "Create My SMTP Credentials". Note the `SMTP_USER` and `SMTP_PASS`.
4. **Set From Address**: Set `SMTP_FROM=noreply@yourdomain.com`.

---

## 5. Security Groups & Network Ingress Rules

| Port | Protocol | Source | Purpose |
| :--- | :--- | :--- | :--- |
| **80** | TCP | `0.0.0.0/0` | HTTP (Redirected to 443 via Nginx / ALB) |
| **443** | TCP | `0.0.0.0/0` | HTTPS Public Traffic (Managed via ALB or Certbot) |
| **8000** | TCP | `Security Group of ALB` or `127.0.0.1` | Direct Uvicorn access (restricted behind reverse proxy) |
| **22** | TCP | `Your Office/VPN IP` | SSH Administrative Access |

---

## 6. Secrets Management Strategy

Do **NOT** commit `.env` files into source control. Choose one of two recommended methods:

### Option A: AWS Systems Manager (SSM) Parameter Store
Store secrets in SSM:
```bash
aws ssm put-parameter --name "/aipod/prod/JWT_SECRET_KEY" --type "SecureString" --value "<64-char-hex>"
aws ssm put-parameter --name "/aipod/prod/SMTP_PASS" --type "SecureString" --value "<ses-pass>"
```
Fetch parameters during EC2 instance boot script (`user_data`) and populate `/etc/aipod.env`.

### Option B: System Environment File
On the EC2 host:
```bash
sudo touch /etc/aipod.env
sudo chown ubuntu:ubuntu /etc/aipod.env
sudo chmod 600 /etc/aipod.env
```
Populate `/etc/aipod.env` with production variables.

---

## 7. Health Check & Monitoring

- **Health Check Route**: `GET /health`
- **Expected Status Code**: `200 OK`
- **Expected Payload**: `{"status": "ok"}`
- **ALB Health Check Path**: `/health` (interval: 15s, timeout: 5s, healthy threshold: 2, unhealthy threshold: 3).

---

## 8. Post-Deployment Verification (Smoke Test)

Immediately after deploying to EC2 and attaching domain/ALB:

Run the automated smoke test suite directly against the production URL:
```bash
python scripts/e2e_smoke_test.py --base-url https://api.yourdomain.com
```

### Expected Output Checklist
- [x] Step 1: Health check GET `/health` returns 200 OK
- [x] Step 2: Generates synthetic transactional dataset
- [x] Step 3: Company signup completes (verifying no secret leakage in response)
- [x] Step 4: Verification and login succeed, issuing session JWT
- [x] Step 5: Onboarding pipeline runs 4-model tournament to completion
- [x] Step 6: Artifacts verified on storage backend (S3/local)
- [x] Step 7: Recommendations return valid items; unknown customer returns fallback 200
- [x] Step 8: Telemetry flusher writes partitioned JSONL files; dashboard analytics aggregate properly
- [x] Step 9: Multi-tenant security checks confirm public key restrictions & zero tenant leakage
- [x] Step 10: API key rotation invalidates old keys and activates new keys immediately

---

## 9. Verification Matrix

| Checklist Item | Local Verification | Real AWS Verification | Next Action |
| :--- | :--- | :--- | :--- |
| **FastAPI Core Serving** | `[VERIFIED LOCALLY]` | `[NOT YET VERIFIED ON AWS]` | Deploy on EC2 t3.large instance |
| **Authentication & Lockout** | `[VERIFIED LOCALLY]` | `[NOT YET VERIFIED ON AWS]` | Test with production domain & SES |
| **Storage Backend (Local)** | `[VERIFIED LOCALLY]` | N/A | Production uses S3 |
| **Storage Backend (S3)** | `[VERIFIED LOCALLY (moto)]` | `[NOT YET VERIFIED ON AWS]` | Run smoke test against real S3 bucket |
| **SES Email Delivery** | `[VERIFIED LOCALLY (mock)]`| `[NOT YET VERIFIED ON AWS]` | Request SES sandbox exit and send live email |
| **Multi-Worker Uvicorn** | `[VERIFIED LOCALLY (multi-thread)]`| `[NOT YET VERIFIED ON AWS]` | Launch systemd unit with `--workers 4` |
| **Telemetry Partitioning** | `[VERIFIED LOCALLY]` | `[NOT YET VERIFIED ON AWS]` | Inspect S3 `data/telemetry/` bucket path |

