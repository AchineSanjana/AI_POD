"""Live end-to-end verification script for C2: Recommendations & Pipeline Catalogue Integration.

Requirements:
1. Start backend: uvicorn src.api.app:app --port 8000
2. Register throwaway account 'E2E Test C2 <rand_hex>'
3. Verify email and log in for JWT token & private API key
4. Upload a small dataset (~300 customers, 40 products, 3,000 interactions)
5. Trigger training via /v1/onboard/train and poll /v1/onboard/status until completed
6. Ensure catalogue is seeded via /v1/catalog/summary
7. Request recommendations: verify 5 items returned with names and categories from catalogue
8. Archive 2 returned products via DELETE /v1/catalog/products/{id}
9. Request recommendations again: verify archived products are GONE and replaced by other active products
10. Restore 1 archived product via POST /v1/catalog/products/{id}/restore: verify it can appear again
11. Add a product via POST /v1/catalog/products: verify GET /v1/catalog/summary reports products_added_since_last_training == 1
12. Retrain tenant via /v1/onboard/train, wait for completion: verify products_added_since_last_training resets to 0
13. Stop server on exit, print each step's result clearly, exit non-zero on failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import os
import pathlib
import random
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd


def wait_for_server(url: str, timeout_sec: int = 30) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def http_json(
    method: str,
    url: str,
    data: dict | None = None,
    headers: dict | None = None,
    timeout: int = 30,
) -> tuple[int, dict | str]:
    headers = dict(headers or {})
    payload_bytes = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        payload_bytes = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=payload_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        try:
            return err.code, json.loads(body)
        except Exception:
            return err.code, body


def generate_synthetic_dataset(
    num_customers: int = 300,
    num_products: int = 40,
    num_interactions: int = 3000,
) -> str:
    """Generate a clean transactional CSV dataset."""
    random.seed(42)
    categories = ["Electronics", "Apparel", "Home", "Books", "Sports"]
    products_meta = []
    for i in range(1, num_products + 1):
        pid = f"PROD_{i:03d}"
        pname = f"Product Item {i:03d}"
        cat = categories[(i - 1) % len(categories)]
        products_meta.append((pid, pname, cat))

    customers = [f"CUST_{c:04d}" for c in range(1, num_customers + 1)]

    lines = ["customer_id,product_id,product_name,category,quantity,timestamp"]
    base_ts = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)

    for i in range(num_interactions):
        cid = random.choice(customers)
        pid, pname, cat = random.choice(products_meta)
        qty = random.randint(1, 5)
        dt = base_ts + pd.Timedelta(minutes=i * 10)
        ts_str = dt.isoformat()
        lines.append(f"{cid},{pid},{pname},{cat},{qty},{ts_str}")

    return "\n".join(lines)


def main():
    print("=" * 70)
    print("STARTING C2 LIVE VERIFICATION: RECOMMENDATIONS & PIPELINE CATALOGUE")
    print("=" * 70)

    server_process = None
    server_log = None
    base_url = "http://127.0.0.1:8000"
    rand_hex = secrets.token_hex(4)
    company_name = f"E2E Test C2 {rand_hex}"
    email = f"e2e_c2_{rand_hex}@example.com"
    password = "LiveCheckPassword123!"

    tenant_id = None

    try:
        # Step 1: Start uvicorn server
        print(f"\n[1] Starting backend uvicorn server on port 8000...")
        env = os.environ.copy()
        env["ENV"] = "development"
        env["AI_POD_ENV"] = "development"
        server_log_path = REPO_ROOT / "live_check_c2_server.log"
        server_log = open(server_log_path, "w", encoding="utf-8")
        server_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.api.app:app", "--port", "8000"],
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )

        ready = wait_for_server(f"{base_url}/api", timeout_sec=30)
        if not ready:
            print("ERROR: Server failed to start within 30s.")
            if server_process.poll() is not None:
                server_log.flush()
                with open(server_log_path, "r", encoding="utf-8") as f:
                    print("Server output:\n", f.read())
            sys.exit(1)
        print("Backend server is UP and responding at http://127.0.0.1:8000")

        # Step 2: Register account
        print(f"\n[2] Registering account: '{company_name}' ({email})...")
        signup_payload = {
            "company_name": company_name,
            "email": email,
            "password": password,
        }
        status, signup_resp = http_json("POST", f"{base_url}/v1/accounts/signup", signup_payload)
        print(f"POST /v1/accounts/signup -> HTTP {status}")
        assert status == 201, f"Signup failed: {signup_resp}"
        tenant_id = signup_resp["tenant_id"]
        account_id = signup_resp["account_id"]
        private_key = signup_resp["private_key"]
        print(f"Created Tenant ID: {tenant_id}, Account ID: {account_id}")

        # Step 3: Fetch dev verification code
        print(f"\n[3] Reading verification code via /v1/accounts/dev/last-verification...")
        status, code_resp = http_json(
            "GET",
            f"{base_url}/v1/accounts/dev/last-verification?email={urllib.parse.quote(email)}",
        )
        assert status == 200, f"Failed getting verification code: {code_resp}"
        code = code_resp["code"]
        print(f"Verification code: {code}")

        # Step 4: Verify email
        print(f"\n[4] Verifying email...")
        status, verify_resp = http_json(
            "POST",
            f"{base_url}/v1/accounts/verify-email",
            {"email": email, "code": code},
        )
        assert status == 200 and verify_resp.get("email_verified") is True, f"Verify email failed: {verify_resp}"
        print("Email successfully verified.")

        # Step 5: Log in for JWT
        print(f"\n[5] Logging in for JWT session token...")
        status, login_resp = http_json(
            "POST",
            f"{base_url}/v1/accounts/login",
            {"email": email, "password": password},
        )
        assert status == 200, f"Login failed: {login_resp}"
        jwt_token = login_resp.get("access_token") or login_resp.get("session_token")
        auth_headers = {
            "Authorization": f"Bearer {jwt_token}",
            "X-API-Key": private_key,
        }
        print("Session token obtained.")

        # Step 6: Upload dataset (~300 customers, 40 products, 3,000 interactions)
        print(f"\n[6] Generating & uploading dataset (300 customers, 40 products, 3,000 interactions)...")
        csv_data = generate_synthetic_dataset(num_customers=300, num_products=40, num_interactions=3000)
        status, upload_resp = http_json(
            "POST",
            f"{base_url}/v1/onboard/upload",
            {"csv_content": csv_data},
            headers=auth_headers,
        )
        assert status == 200, f"Upload failed: {upload_resp}"
        print(f"Uploaded: {upload_resp['rows']} rows, {len(upload_resp['columns'])} columns.")

        # Step 7: Validate & Confirm Onboarding Config
        print(f"\n[7] Profiling & confirming tenant configuration...")
        status, val_resp = http_json("POST", f"{base_url}/v1/onboard/validate", headers=auth_headers)
        assert status == 200, f"Validate failed: {val_resp}"
        candidate_cfg = val_resp["candidate_config"]

        status, conf_resp = http_json(
            "POST",
            f"{base_url}/v1/onboard/confirm",
            {"candidate_config": candidate_cfg},
            headers=auth_headers,
        )
        assert status == 200 and conf_resp.get("config_saved") is True, f"Confirm failed: {conf_resp}"
        print("Tenant configuration confirmed and persisted to config.yaml.")

        # Step 8: Trigger Training and Poll Status
        print(f"\n[8] Triggering training via POST /v1/onboard/train...")
        status, tr_resp = http_json("POST", f"{base_url}/v1/onboard/train", headers=auth_headers)
        assert status == 202, f"Train request failed: {tr_resp}"
        print("Training initiated. Polling /v1/onboard/status...")

        poll_start = time.time()
        final_status = None
        while time.time() - poll_start < 120:
            status, s_resp = http_json("GET", f"{base_url}/v1/onboard/status", headers=auth_headers)
            if status == 200:
                current_stage = s_resp.get("stage")
                current_state = s_resp.get("status")
                print(f"   Status: {current_state} (Stage: {current_stage}) - {s_resp.get('message')}")
                if current_state == "completed":
                    final_status = s_resp
                    break
                elif current_state == "failed":
                    raise RuntimeError(f"Training failed: {s_resp.get('error')}")
            time.sleep(2.0)

        assert final_status is not None, "Training did not complete within timeout."
        winner = final_status.get("winner_model") or final_status.get("winner_key")
        print(f"Training completed successfully! Winning model: {winner}")

        # Step 9: Seed catalogue on first access via /v1/catalog/summary
        print(f"\n[9] Initializing catalogue via GET /v1/catalog/summary...")
        status, sum_resp = http_json("GET", f"{base_url}/v1/catalog/summary", headers=auth_headers)
        assert status == 200, f"Summary failed: {sum_resp}"
        print(f"Catalogue Summary: active={sum_resp['active']}, archived={sum_resp['archived']}, added_since_train={sum_resp['products_added_since_last_training']}")
        assert sum_resp["active"] == 40
        assert sum_resp["products_added_since_last_training"] == 0

        # Step 10: Request recommendations: verify 5 items returned with names and categories from catalogue
        print(f"\n[10] Requesting recommendations for customer 'CUST_0001'...")
        rec_url = f"{base_url}/v1/recommendations?customer_id=CUST_0001&top_n=5"
        status, rec_resp = http_json("GET", rec_url, headers=auth_headers)
        assert status == 200, f"Recommendations failed: {rec_resp}"
        recs = rec_resp["recommendations"]
        assert len(recs) == 5, f"Expected 5 recommendations, got {len(recs)}"
        print(f"Received 5 recommendations:")
        for r in recs:
            print(f"   - {r['product_id']}: '{r['product_name']}' (Category: {r['category']})")
            assert r["product_name"] and r["product_name"] != r["product_id"], f"Missing catalogue name: {r}"
            assert r["category"], f"Missing category: {r}"

        # Step 11: Archive 2 returned products via DELETE /v1/catalog/products/{id}
        prod_to_archive_1 = recs[0]["product_id"]
        prod_to_archive_2 = recs[1]["product_id"]
        print(f"\n[11] Archiving products '{prod_to_archive_1}' and '{prod_to_archive_2}'...")
        status, d1 = http_json("DELETE", f"{base_url}/v1/catalog/products/{prod_to_archive_1}", headers=auth_headers)
        assert status == 200, f"Delete {prod_to_archive_1} failed: {d1}"
        status, d2 = http_json("DELETE", f"{base_url}/v1/catalog/products/{prod_to_archive_2}", headers=auth_headers)
        assert status == 200, f"Delete {prod_to_archive_2} failed: {d2}"
        print("Both products archived.")

        # Step 12: Request recommendations again: verify archived products are GONE and replaced by other active products
        print(f"\n[12] Verifying archived products are excluded from recommendations...")
        status, rec_resp_2 = http_json("GET", rec_url, headers=auth_headers)
        assert status == 200, f"Recommendations after archive failed: {rec_resp_2}"
        recs_2 = rec_resp_2["recommendations"]
        pids_2 = [r["product_id"] for r in recs_2]
        print(f"New recommendations: {pids_2}")
        assert prod_to_archive_1 not in pids_2, f"Archived product {prod_to_archive_1} still in recommendations!"
        assert prod_to_archive_2 not in pids_2, f"Archived product {prod_to_archive_2} still in recommendations!"
        assert len(recs_2) == 5, f"Recommendations were not topped up to 5 items: {len(recs_2)}"
        print("Archived products successfully excluded and replaced by active products.")

        # Step 13: Restore 1 of them via POST /v1/catalog/products/{id}/restore
        print(f"\n[13] Restoring product '{prod_to_archive_1}'...")
        status, rest_resp = http_json("POST", f"{base_url}/v1/catalog/products/{prod_to_archive_1}/restore", headers=auth_headers)
        assert status == 200, f"Restore failed: {rest_resp}"
        assert rest_resp["status"] == "active"
        print(f"Product '{prod_to_archive_1}' restored to active status.")

        # Step 14: Add a new product via POST /v1/catalog/products
        print(f"\n[14] Adding new product 'PROD_NEW_999' to catalogue...")
        new_prod_payload = {
            "product_id": "PROD_NEW_999",
            "product_name": "Brand New Active Item 999",
            "category": "Electronics",
            "price": 299.99,
        }
        status, add_resp = http_json("POST", f"{base_url}/v1/catalog/products", new_prod_payload, headers=auth_headers)
        assert status == 201, f"Add product failed: {add_resp}"

        # Verify GET /v1/catalog/summary reports products_added_since_last_training == 1
        status, sum_after_add = http_json("GET", f"{base_url}/v1/catalog/summary", headers=auth_headers)
        assert status == 200, f"Summary failed: {sum_after_add}"
        print(f"Summary after add: products_added_since_last_training={sum_after_add['products_added_since_last_training']}")
        assert sum_after_add["products_added_since_last_training"] == 1, (
            f"Expected products_added_since_last_training == 1, got {sum_after_add['products_added_since_last_training']}"
        )

        # Step 15: Retrain tenant via /v1/onboard/train
        print(f"\n[15] Retraining tenant via POST /v1/onboard/train...")
        status, tr2_resp = http_json("POST", f"{base_url}/v1/onboard/train", headers=auth_headers)
        assert status == 202, f"Retrain failed: {tr2_resp}"

        poll_start = time.time()
        while time.time() - poll_start < 120:
            status, s_resp = http_json("GET", f"{base_url}/v1/onboard/status", headers=auth_headers)
            if status == 200 and s_resp.get("status") == "completed":
                print(f"Retraining completed: {s_resp.get('message')}")
                break
            time.sleep(2.0)

        # Verify products_added_since_last_training resets to 0
        status, sum_after_retrain = http_json("GET", f"{base_url}/v1/catalog/summary", headers=auth_headers)
        assert status == 200, f"Summary after retrain failed: {sum_after_retrain}"
        print(f"Summary after retrain: products_added_since_last_training={sum_after_retrain['products_added_since_last_training']}")
        assert sum_after_retrain["products_added_since_last_training"] == 0, (
            f"Expected products_added_since_last_training == 0 after retrain, got {sum_after_retrain['products_added_since_last_training']}"
        )

        print("\n" + "=" * 70)
        print("ALL C2 LIVE VERIFICATION CHECKS PASSED SUCCESSFULLY!")
        print(f"Throwaway Tenant ID: {tenant_id}")
        print("=" * 70)

    except Exception as exc:
        print(f"\nFATAL ERROR DURING C2 LIVE CHECK: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if server_process is not None:
            print("\nShutting down backend uvicorn server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
            print("Server stopped cleanly.")
        if server_log is not None:
            try:
                server_log.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()

