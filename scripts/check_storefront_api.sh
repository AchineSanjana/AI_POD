#!/usr/bin/env bash
# AI_POD Storefront API Diagnostics (Bash/curl)
# Usage:
#   bash scripts/check_storefront_api.sh [base_url] [public_key] [customer_id]

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
PUBLIC_KEY="${2:-pk-fresh_cart_co-375554e8b1aa}"
CUSTOMER_ID="${3:-2455}"
ORIGIN="${BASE_URL%/}"

echo "========================================================================"
echo "AI_POD Storefront API Diagnostics"
echo "Base URL    : ${BASE_URL}"
echo "Public Key  : ${PUBLIC_KEY}"
echo "Customer ID : ${CUSTOMER_ID}"
echo "Origin      : ${ORIGIN}"
echo "========================================================================"
echo ""

echo "[1/2] Sending OPTIONS preflight to: ${BASE_URL}/v1/recommendations"
curl -s -i -X OPTIONS "${BASE_URL}/v1/recommendations" \
  -H "Origin: ${ORIGIN}" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: X-API-Key" | \
  grep -i -E "(HTTP/|access-control)" || true

echo ""
echo "[2/2] Sending GET recommendations to: ${BASE_URL}/v1/recommendations"
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}\n" -X GET "${BASE_URL}/v1/recommendations?customer_id=${CUSTOMER_ID}&top_n=5" \
  -H "X-API-Key: ${PUBLIC_KEY}" \
  -H "Origin: ${ORIGIN}" \
  -H "Accept: application/json")

HTTP_STATUS=$(echo "${RESPONSE}" | grep "HTTP_STATUS:" | cut -d':' -f2)
BODY=$(echo "${RESPONSE}" | grep -v "HTTP_STATUS:")

echo "Status Code : ${HTTP_STATUS}"
echo "Response Body:"
echo "${BODY}"
echo ""

if echo "${BODY}" | grep -q '"fallback":true'; then
  echo "VERDICT: Returned recommendations via POPULARITY FALLBACK (fallback: true)."
elif echo "${BODY}" | grep -q '"fallback":false'; then
  echo "VERDICT: Returned recommendations via TRAINED ML MODEL (fallback: false)."
else
  echo "VERDICT: Check status and body above."
fi
