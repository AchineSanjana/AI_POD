# Container Redeployment Guide: `ai-pod-api`

This document details the exact process to rebuild the updated `ai-pod-api` Docker image (incorporating API-key authentication, rate limiting, and `/v1/` versioned routes), push it to AWS Elastic Container Registry (ECR), and redeploy it on the EC2 instance without downtime or infrastructure changes.

---

## 1. Registry & Environment Parameters

| Parameter | Value |
| :--- | :--- |
| **AWS Account ID** | `772325758824` |
| **AWS Region** | `ap-south-1` (Mumbai) |
| **ECR Repository** | `ai-pod-api` |
| **ECR URI** | `772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api` |
| **Image Tags** | `:latest`, `:v2-auth-ratelimit` |
| **Container Port** | `8000` |

---

## 2. Rebuild & Push Image to ECR

Run these commands from your local development machine or CI/CD build runner with Docker and AWS CLI installed:

### Step 2.1: Authenticate Docker with Amazon ECR
```bash
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin 772325758824.dkr.ecr.ap-south-1.amazonaws.com
```

### Step 2.2: Build the Container Image
The `Dockerfile` remains unchanged and bundles the latest application source, versioned routes, authentication dependencies, and rate limiter:

```bash
docker build \
  -t ai-pod-api:latest \
  -t 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:latest \
  -t 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:v2-auth-ratelimit \
  .
```

### Step 2.3: Push to ECR
```bash
docker push 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:latest
docker push 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:v2-auth-ratelimit
```

---

## 3. Redeploy on the EC2 Instance

SSH into the EC2 host and execute the following commands to pull the latest image and restart the container:

### Step 3.1: Authenticate Docker on EC2
```bash
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin 772325758824.dkr.ecr.ap-south-1.amazonaws.com
```

### Step 3.2: Pull the Updated Image
```bash
docker pull 772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:latest
```

### Step 3.3: Stop & Remove the Existing Container
```bash
docker stop ai-pod-api && docker rm ai-pod-api
```

### Step 3.4: Run the New Container
```bash
docker run -d \
  --name ai-pod-api \
  --restart unless-stopped \
  -p 8000:8000 \
  -e STORAGE_BACKEND=s3 \
  -e STORAGE_S3_BUCKET=ai-pod-storage-772325758824 \
  -e AWS_DEFAULT_REGION=ap-south-1 \
  -e TENANTS_AUTH_PARAM_NAME=/ai_pod/tenants_auth \
  772325758824.dkr.ecr.ap-south-1.amazonaws.com/ai-pod-api:latest
```

---

## 4. Verification & Smoke Test

Confirm the container is healthy and verify the upgraded `/v1/` route:

### 4.1 Check Container Status & Logs
```bash
docker ps --filter "name=ai-pod-api"
docker logs ai-pod-api --tail 50
```

### 4.2 Query Healthcheck Endpoint
```bash
curl -i http://localhost:8000/health
```
**Expected Response**: `HTTP/1.1 200 OK`
```json
{"status": "ok"}
```

### 4.3 Verify Existing `telco_default` Tenant through `/v1/recommendations`
Prove the existing default deployment remains fully functional under the new API-key authentication and versioned route:

```bash
curl -i -H "X-API-Key: sk-telco-xxxx" \
  "http://localhost:8000/v1/recommendations?customer_id=7590-VHVEG&top_n=5"
```

**Expected Response**: `HTTP/1.1 200 OK`
```json
{
  "tenant_id": "telco_default",
  "customer_id": "7590-VHVEG",
  "recommendations": [
    {
      "rank": 1,
      "product_id": "OnlineSecurity",
      "product_name": "OnlineSecurity",
      "category": null
    },
    {
      "rank": 2,
      "product_id": "TechSupport",
      "product_name": "TechSupport",
      "category": null
    },
    {
      "rank": 3,
      "product_id": "OnlineBackup",
      "product_name": "OnlineBackup",
      "category": null
    },
    {
      "rank": 4,
      "product_id": "DeviceProtection",
      "product_name": "DeviceProtection",
      "category": null
    },
    {
      "rank": 5,
      "product_id": "StreamingMovies",
      "product_name": "StreamingMovies",
      "category": null
    }
  ]
}
```

### 4.4 Verify Auth Enforcement (Negative Test)
Confirm unauthenticated requests are strictly rejected:
```bash
curl -i "http://localhost:8000/v1/recommendations?customer_id=7590-VHVEG&top_n=5"
```
**Expected Response**: `HTTP/1.1 401 Unauthorized`
```json
{
  "detail": "API key is missing. Provide a valid 'X-API-Key' header."
}
```
