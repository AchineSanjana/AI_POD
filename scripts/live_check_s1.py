"""Live end-to-end verification script for S1: Similar Products Subsystem.

Steps:
1. Start backend server: uvicorn src.api.app:app --port 8000
2. Register throwaway company account 'E2E Test S1 <rand_hex>'
3. Fetch verification code and verify email
4. Log in for session JWT token
5. Prepare CSV with >= 30 products across 3 categories (Smartphones, Laptops, Audio) with specs and prices
6. Upload CSV (POST /v1/catalog/upload) and commit (POST /v1/catalog/upload/{upload_id}/commit)
7. Query similar products (GET /v1/recommendations/similar/{product_id}) for 3 distinct items
8. Print rankings and human-readable reasons for each item
9. Archive one recommended product (DELETE /v1/catalog/products/{id}) and show it disappears from results
10. Add a new product (POST /v1/catalog/products) and show it appears in similar results
11. Output throwaway tenant ID and results summary
"""

from __future__ import annotations

import io
import json
import os
import pathlib
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


def http_multipart(
    url: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
    headers: dict | None = None,
    timeout: int = 30,
) -> tuple[int, dict | str]:
    boundary = f"----WebKitFormBoundary{secrets.token_hex(16)}"
    headers = dict(headers or {})
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    body = io.BytesIO()
    for field_name, val in fields.items():
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode("utf-8"))
        body.write(f"{val}\r\n".encode("utf-8"))

    for field_name, (filename, file_bytes, content_type) in files.items():
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8"))
        body.write(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.write(file_bytes)
        body.write(b"\r\n")

    body.write(f"--{boundary}--\r\n".encode("utf-8"))
    payload = body.getvalue()

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res_body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(res_body)
            except Exception:
                return resp.status, res_body
    except urllib.error.HTTPError as err:
        res_body = err.read().decode("utf-8")
        try:
            return err.code, json.loads(res_body)
        except Exception:
            return err.code, res_body


def main():
    print("=" * 80)
    print("STARTING S1 SIMILAR PRODUCTS LIVE VERIFICATION")
    print("=" * 80)

    server_process = None
    base_url = "http://127.0.0.1:8000"
    rand_hex = secrets.token_hex(4)
    company_name = f"E2E Test S1 {rand_hex}"
    email = f"e2e_s1_{rand_hex}@example.com"
    password = "LiveCheckPassword123!"

    try:
        # Step 1: Start uvicorn server
        print(f"\n[1] Starting backend uvicorn on port 8000...")
        env = os.environ.copy()
        env["ENV"] = "development"
        env["AI_POD_ENV"] = "development"
        server_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.api.app:app", "--port", "8000"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        ready = wait_for_server(f"{base_url}/health", timeout_sec=30)
        if not ready:
            print("ERROR: Server failed to start within 30s.")
            if server_process.poll() is not None:
                out, _ = server_process.communicate()
                print("Server output:\n", out)
            sys.exit(1)
        print("Backend server is UP and responding at http://127.0.0.1:8000")

        # Step 2: Sign up throwaway account
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
        print(f"Created Account ID: {account_id}, Tenant ID: {tenant_id}")

        # Step 3: Fetch dev verification code & verify email
        print(f"\n[3] Reading verification code via /v1/accounts/dev/last-verification...")
        status, code_resp = http_json("GET", f"{base_url}/v1/accounts/dev/last-verification?email={urllib.parse.quote(email)}")
        assert status == 200, f"Failed getting verification code: {code_resp}"
        code = code_resp["code"]
        print(f"Verification code received: {code}")

        print(f"Verifying email address...")
        verify_payload = {"email": email, "code": code}
        status, verify_resp = http_json("POST", f"{base_url}/v1/accounts/verify-email", verify_payload)
        assert status == 200, f"Email verification failed: {verify_resp}"
        assert verify_resp.get("email_verified") is True
        print("Email verified successfully.")

        # Step 4: Log in for JWT session token
        print(f"\n[4] Logging in for session JWT...")
        login_payload = {"email": email, "password": password}
        status, login_resp = http_json("POST", f"{base_url}/v1/accounts/login", login_payload)
        assert status == 200, f"Login failed: {login_resp}"
        jwt_token = login_resp.get("access_token") or login_resp.get("session_token")
        auth_headers = {"Authorization": f"Bearer {jwt_token}"}
        print("JWT session authenticated.")

        # Retrieve keys from signup response & verify profile
        sk_key = signup_resp.get("private_key")
        pk_key = signup_resp.get("public_key")
        assert pk_key, "No public key returned in signup response"

        status, me_resp = http_json("GET", f"{base_url}/v1/accounts/me", headers=auth_headers)
        assert status == 200, f"Failed getting account profile: {me_resp}"
        me_pk = me_resp.get("public_key")
        assert me_pk == pk_key, f"Public key mismatch: {me_pk} vs {pk_key}"
        print(f"Tenant Keys Verified: PK={pk_key[:16]}... (SK issued: {bool(sk_key)})")

        # Step 5: Build catalogue with 30 items across 3 categories
        print(f"\n[5] Generating 30 products dataset across 3 categories with specs and prices...")
        products = [
            # 10 Smartphones
            {"product_id": "SP-01", "product_name": "Apple iPhone 15 Pro", "category": "Smartphones", "brand": "Apple", "price": 999.0, "in_stock": 1, "specs": "ram_gb=8; storage_gb=128; screen_in=6.1", "description": "Flagship Apple iPhone with titanium design and A17 Pro chip"},
            {"product_id": "SP-02", "product_name": "Apple iPhone 15", "category": "Smartphones", "brand": "Apple", "price": 799.0, "in_stock": 1, "specs": "ram_gb=6; storage_gb=128; screen_in=6.1", "description": "Standard Apple iPhone with Dynamic Island and 48MP camera"},
            {"product_id": "SP-03", "product_name": "Samsung Galaxy S24 Ultra", "category": "Smartphones", "brand": "Samsung", "price": 1299.0, "in_stock": 1, "specs": "ram_gb=12; storage_gb=256; screen_in=6.8", "description": "Ultimate Galaxy smartphone with S Pen and AI camera"},
            {"product_id": "SP-04", "product_name": "Samsung Galaxy S24", "category": "Smartphones", "brand": "Samsung", "price": 799.0, "in_stock": 1, "specs": "ram_gb=8; storage_gb=128; screen_in=6.2", "description": "Compact Samsung flagship with Galaxy AI capabilities"},
            {"product_id": "SP-05", "product_name": "Samsung Galaxy A54", "category": "Smartphones", "brand": "Samsung", "price": 449.0, "in_stock": 1, "specs": "ram_gb=6; storage_gb=128; screen_in=6.4", "description": "Mid-range Samsung smartphone with Super AMOLED display"},
            {"product_id": "SP-06", "product_name": "Google Pixel 8 Pro", "category": "Smartphones", "brand": "Google", "price": 999.0, "in_stock": 1, "specs": "ram_gb=12; storage_gb=128; screen_in=6.7", "description": "Google flagship phone with pro camera and Tensor G3"},
            {"product_id": "SP-07", "product_name": "Google Pixel 8", "category": "Smartphones", "brand": "Google", "price": 699.0, "in_stock": 1, "specs": "ram_gb=8; storage_gb=128; screen_in=6.2", "description": "Everyday Google phone with advanced AI photo tools"},
            {"product_id": "SP-08", "product_name": "OnePlus 12", "category": "Smartphones", "brand": "OnePlus", "price": 799.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=256; screen_in=6.82", "description": "Fast and smooth smartphone with Snapdragon 8 Gen 3"},
            {"product_id": "SP-09", "product_name": "Xiaomi 14", "category": "Smartphones", "brand": "Xiaomi", "price": 749.0, "in_stock": 1, "specs": "ram_gb=12; storage_gb=256; screen_in=6.36", "description": "Compact Leica camera smartphone with fast charging"},
            {"product_id": "SP-10", "product_name": "Sony Xperia 1 V", "category": "Smartphones", "brand": "Sony", "price": 1199.0, "in_stock": 1, "specs": "ram_gb=12; storage_gb=256; screen_in=6.5", "description": "Pro cinematography smartphone with 4K HDR OLED display"},

            # 10 Laptops
            {"product_id": "LP-01", "product_name": "Apple MacBook Pro 16", "category": "Laptops", "brand": "Apple", "price": 2499.0, "in_stock": 1, "specs": "ram_gb=36; storage_gb=512; screen_in=16.2; cpu_cores=14", "description": "Pro laptop with M3 Pro chip for creative workflows"},
            {"product_id": "LP-02", "product_name": "Apple MacBook Air 13", "category": "Laptops", "brand": "Apple", "price": 1099.0, "in_stock": 1, "specs": "ram_gb=8; storage_gb=256; screen_in=13.6; cpu_cores=8", "description": "Ultra-thin lightweight Apple laptop with M3 chip"},
            {"product_id": "LP-03", "product_name": "Dell XPS 15", "category": "Laptops", "brand": "Dell", "price": 1899.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=512; screen_in=15.6; cpu_cores=14", "description": "Premium Windows laptop with InfinityEdge OLED screen"},
            {"product_id": "LP-04", "product_name": "Dell XPS 13", "category": "Laptops", "brand": "Dell", "price": 1199.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=512; screen_in=13.4; cpu_cores=12", "description": "Compact premium ultrabook for mobile professionals"},
            {"product_id": "LP-05", "product_name": "Lenovo ThinkPad X1 Carbon", "category": "Laptops", "brand": "Lenovo", "price": 1749.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=512; screen_in=14.0; cpu_cores=12", "description": "Enterprise business ultrabook with legendary keyboard"},
            {"product_id": "LP-06", "product_name": "Lenovo ThinkPad T14", "category": "Laptops", "brand": "Lenovo", "price": 1299.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=256; screen_in=14.0; cpu_cores=8", "description": "Durable corporate workstation with reliable security"},
            {"product_id": "LP-07", "product_name": "Asus ROG Zephyrus G14", "category": "Laptops", "brand": "Asus", "price": 1599.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=1024; screen_in=14.0; cpu_cores=8", "description": "Compact powerful gaming laptop with OLED display"},
            {"product_id": "LP-08", "product_name": "HP Spectre x360", "category": "Laptops", "brand": "HP", "price": 1449.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=512; screen_in=14.0; cpu_cores=14", "description": "Convertible 2-in-1 laptop with sleek gem-cut design"},
            {"product_id": "LP-09", "product_name": "Razer Blade 15", "category": "Laptops", "brand": "Razer", "price": 2199.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=1024; screen_in=15.6; cpu_cores=14", "description": "High performance gaming laptop with CNC aluminum chassis"},
            {"product_id": "LP-10", "product_name": "Lenovo Yoga 9i", "category": "Laptops", "brand": "Lenovo", "price": 1399.0, "in_stock": 1, "specs": "ram_gb=16; storage_gb=512; screen_in=14.0; cpu_cores=12", "description": "Premium 2-in-1 convertible with rotating soundbar"},

            # 10 Audio
            {"product_id": "AD-01", "product_name": "Sony WH-1000XM5", "category": "Audio", "brand": "Sony", "price": 399.0, "in_stock": 1, "specs": "battery_mah=1200; weight_g=250", "description": "Industry leading noise canceling wireless headphones"},
            {"product_id": "AD-02", "product_name": "Sony WF-1000XM5", "category": "Audio", "brand": "Sony", "price": 299.0, "in_stock": 1, "specs": "battery_mah=500; weight_g=59", "description": "Truly wireless noise canceling earbuds with high-res audio"},
            {"product_id": "AD-03", "product_name": "Bose QuietComfort Ultra", "category": "Audio", "brand": "Bose", "price": 429.0, "in_stock": 1, "specs": "battery_mah=1100; weight_g=254", "description": "World class noise cancellation with immersive spatial audio"},
            {"product_id": "AD-04", "product_name": "Bose QuietComfort 45", "category": "Audio", "brand": "Bose", "price": 329.0, "in_stock": 1, "specs": "battery_mah=900; weight_g=240", "description": "Iconic comfortable noise cancelling wireless headphones"},
            {"product_id": "AD-05", "product_name": "Apple AirPods Max", "category": "Audio", "brand": "Apple", "price": 549.0, "in_stock": 1, "specs": "battery_mah=1300; weight_g=384", "description": "Over-ear luxury headphones with high-fidelity spatial audio"},
            {"product_id": "AD-06", "product_name": "Apple AirPods Pro 2", "category": "Audio", "brand": "Apple", "price": 249.0, "in_stock": 1, "specs": "battery_mah=523; weight_g=50", "description": "Active noise cancellation earbuds with USB-C MagSafe case"},
            {"product_id": "AD-07", "product_name": "Sennheiser Momentum 4", "category": "Audio", "brand": "Sennheiser", "price": 379.0, "in_stock": 1, "specs": "battery_mah=700; weight_g=293", "description": "Audiophile sound quality with 60-hour battery life"},
            {"product_id": "AD-08", "product_name": "Sennheiser HD 660S2", "category": "Audio", "brand": "Sennheiser", "price": 499.0, "in_stock": 1, "specs": "weight_g=260", "description": "Open-back wired headphones for analytical listening"},
            {"product_id": "AD-09", "product_name": "JBL Flip 6", "category": "Audio", "brand": "JBL", "price": 129.0, "in_stock": 1, "specs": "battery_mah=4800; weight_g=550", "description": "Portable waterproof Bluetooth speaker with bold sound"},
            {"product_id": "AD-10", "product_name": "Marshall Stanmore III", "category": "Audio", "brand": "Marshall", "price": 379.0, "in_stock": 1, "specs": "weight_g=4250", "description": "Classic vintage home Bluetooth stereo speaker"},
        ]

        df_upload = pd.DataFrame(products)
        csv_bytes = df_upload.to_csv(index=False).encode("utf-8")

        # Step 6: Upload and Commit Catalogue
        print(f"\n[6] Uploading 30 products via POST /v1/catalog/upload...")
        status, upload_resp = http_multipart(
            f"{base_url}/v1/catalog/upload",
            fields={"mode": "replace"},
            files={"file": ("products.csv", csv_bytes, "text/csv")},
            headers=auth_headers,
        )
        assert status == 200, f"Upload preview failed: {upload_resp}"
        upload_id = upload_resp["upload_id"]
        total_rows = upload_resp["total_rows"]
        print(f"Upload Preview -> upload_id: {upload_id}, total_rows: {total_rows}")
        assert total_rows == 30, f"Expected 30 valid rows, got {total_rows}"

        print(f"Committing upload {upload_id} via POST /v1/catalog/upload/{upload_id}/commit...")
        status, commit_resp = http_json(
            "POST",
            f"{base_url}/v1/catalog/upload/{upload_id}/commit",
            data={},
            headers=auth_headers,
        )
        assert status == 200, f"Upload commit failed: {commit_resp}"
        applied_rows = commit_resp["applied"]
        print(f"Committed {applied_rows} products successfully.")
        assert applied_rows == 30

        # Step 7: Query similar products for 3 items
        print(f"\n[7] Querying similar products for 3 items...")
        test_items = [
            ("SP-01", "Apple iPhone 15 Pro (Smartphones)"),
            ("LP-01", "Apple MacBook Pro 16 (Laptops)"),
            ("AD-01", "Sony WH-1000XM5 (Audio)"),
        ]

        for pid, label in test_items:
            print(f"\n---> Querying Similar Products for: {pid} - {label}")
            status, sim_resp = http_json(
                "GET",
                f"{base_url}/v1/recommendations/similar/{pid}?top_n=3&same_category=true&max_price_ratio=2.0",
                headers={"X-API-Key": pk_key},
            )
            assert status == 200, f"Similar query failed: {sim_resp}"
            assert sim_resp["fallback"] is False, f"Expected non-fallback result, got {sim_resp}"
            print(f"Target: {sim_resp['product_name']} (ID: {sim_resp['product_id']})")
            print(f"Rankings returned ({len(sim_resp['similar'])} items):")
            for item in sim_resp["similar"]:
                print(f"   Rank #{item['rank']}: [{item['product_id']}] {item['product_name']} | Brand: {item['brand']} | Price: ${item['price']} | Sim: {item['similarity']} | Reasons: {', '.join(item['reasons'])}")

        # Step 8: Archive one product and show it disappears
        print(f"\n[8] Archiving product 'SP-02' (Apple iPhone 15)...")
        status, del_resp = http_json("DELETE", f"{base_url}/v1/catalog/products/SP-02", headers=auth_headers)
        assert status == 200, f"Archive failed: {del_resp}"
        assert del_resp["status"] == "archived"
        print("Product SP-02 archived successfully.")

        # Re-query SP-01 similar products
        print("Re-querying similar products for SP-01 to verify SP-02 disappeared...")
        status, sim_resp_post_del = http_json(
            "GET",
            f"{base_url}/v1/recommendations/similar/SP-01?top_n=4",
            headers={"X-API-Key": pk_key},
        )
        assert status == 200
        pids_post_del = [item["product_id"] for item in sim_resp_post_del["similar"]]
        print(f"Updated similar product IDs for SP-01: {pids_post_del}")
        assert "SP-02" not in pids_post_del, f"Archived product SP-02 still in similar results: {pids_post_del}"
        print("Confirmed: Archived product 'SP-02' disappeared from similar results!")

        # Step 9: Add a new product and show it appears
        print(f"\n[9] Adding new product 'SP-99' (Apple iPhone 15 Ultra)...")
        new_product_payload = {
            "product_id": "SP-99",
            "product_name": "Apple iPhone 15 Ultra",
            "category": "Smartphones",
            "brand": "Apple",
            "price": 1099.0,
            "in_stock": 1,
            "specs": "ram_gb=8; storage_gb=256; screen_in=6.7",
            "description": "Ultra premium Apple smartphone with titanium finish and A17 Pro",
        }
        status, add_resp = http_json("POST", f"{base_url}/v1/catalog/products", new_product_payload, headers=auth_headers)
        assert status == 201, f"Add product failed: {add_resp}"
        print(f"Product SP-99 created successfully.")

        # Query similar products for SP-01 again to verify SP-99 appears
        print("Re-querying similar products for SP-01 to verify SP-99 appears...")
        status, sim_resp_post_add = http_json(
            "GET",
            f"{base_url}/v1/recommendations/similar/SP-01?top_n=4",
            headers={"X-API-Key": pk_key},
        )
        assert status == 200
        pids_post_add = [item["product_id"] for item in sim_resp_post_add["similar"]]
        print(f"Updated similar product IDs for SP-01: {pids_post_add}")
        assert "SP-99" in pids_post_add, f"New product SP-99 not found in similar results: {pids_post_add}"
        matching_item = next(it for it in sim_resp_post_add["similar"] if it["product_id"] == "SP-99")
        print(f"Confirmed: New product 'SP-99' appeared at Rank #{matching_item['rank']} with similarity {matching_item['similarity']} and reasons: {matching_item['reasons']}")

        print("\n" + "=" * 80)
        print("ALL S1 LIVE VERIFICATION CHECKS COMPLETED AND PASSED!")
        print(f"Throwaway Tenant ID: {tenant_id}")
        print("=" * 80)

    finally:
        if server_process is not None:
            print("\nShutting down backend server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
            print("Server stopped.")


if __name__ == "__main__":
    main()

