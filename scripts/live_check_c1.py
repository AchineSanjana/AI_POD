"""Live end-to-end verification script for C1 Tenant-Managed Product Catalogue.

Steps:
1. Start backend: uvicorn src.api.app:app --port 8000
2. Register throwaway account 'E2E Test C1 <rand_hex>'
3. Fetch verification code via /v1/accounts/dev/last-verification
4. Verify email
5. Log in for JWT access token
6. Seed data/processed/<tenant>/products.csv with 4 products via StorageBackend
7. Call GET /v1/catalog/summary -> verify data/catalog/<tenant>/catalog.csv auto-seeded
8. Exercise Add, Edit, Archive, Restore
9. Exercise Template, Upload Preview & Commit (upsert mode)
10. Exercise History and Snapshot Undo
11. Shut down uvicorn and output throwaway tenant ID for user cleanup
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
import urllib.request
import urllib.parse

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


def http_json(method: str, url: str, data: dict | None = None, headers: dict | None = None) -> tuple[int, dict | str]:
    headers = dict(headers or {})
    payload_bytes = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        payload_bytes = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=payload_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
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


def http_multipart(url: str, files: dict[str, tuple[str, bytes, str]], data: dict[str, str], headers: dict | None = None) -> tuple[int, dict | str]:
    boundary = f"----WebKitFormBoundary{secrets.token_hex(16)}"
    headers = dict(headers or {})
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    body = io.BytesIO()
    for field_name, val in data.items():
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
        with urllib.request.urlopen(req, timeout=10) as resp:
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
    print("=" * 70)
    print("STARTING C1 LIVE VERIFICATION")
    print("=" * 70)

    server_process = None
    base_url = "http://127.0.0.1:8000"
    rand_hex = secrets.token_hex(4)
    company_name = f"E2E Test C1 {rand_hex}"
    email = f"e2e_c1_{rand_hex}@example.com"
    password = "LiveCheckPassword123!"

    try:
        # Step 1: Start uvicorn server
        print(f"\n[1] Starting uvicorn on port 8000...")
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

        ready = wait_for_server(f"{base_url}/api", timeout_sec=30)
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

        # Step 3: Fetch dev verification code
        print(f"\n[3] Reading verification code via /v1/accounts/dev/last-verification...")
        status, code_resp = http_json("GET", f"{base_url}/v1/accounts/dev/last-verification?email={urllib.parse.quote(email)}")
        print(f"GET /v1/accounts/dev/last-verification -> HTTP {status}")
        assert status == 200, f"Failed getting verification code: {code_resp}"
        code = code_resp["code"]
        print(f"Verification code received: {code}")

        # Step 4: Verify email
        print(f"\n[4] Verifying email address...")
        verify_payload = {"email": email, "code": code}
        status, verify_resp = http_json("POST", f"{base_url}/v1/accounts/verify-email", verify_payload)
        print(f"POST /v1/accounts/verify-email -> HTTP {status}")
        assert status == 200, f"Email verification failed: {verify_resp}"
        assert verify_resp.get("email_verified") is True

        # Step 5: Log in for JWT session token
        print(f"\n[5] Logging in for session JWT...")
        login_payload = {"email": email, "password": password}
        status, login_resp = http_json("POST", f"{base_url}/v1/accounts/login", login_payload)
        print(f"POST /v1/accounts/login -> HTTP {status}")
        assert status == 200, f"Login failed: {login_resp}"
        jwt_token = login_resp.get("access_token") or login_resp.get("session_token")
        assert jwt_token, "No JWT token in login response"
        auth_headers = {"Authorization": f"Bearer {jwt_token}"}
        print(f"JWT session established successfully.")

        # Step 6: Create data/processed/<tenant>/products.csv through storage layer first
        print(f"\n[6] Seeding data/processed/{tenant_id}/products.csv via storage backend...")
        from src.storage import get_storage_backend
        storage = get_storage_backend()
        proc_path = f"data/processed/{tenant_id}/products.csv"
        sample_df = pd.DataFrame([
            {"product_id": "LIVE-P1", "product_name": "Premium Wireless Mouse", "category": "Accessories", "price": 49.99},
            {"product_id": "LIVE-P2", "title": "Mechanical Gaming Keyboard", "product_type": "Keyboards", "price": 129.99},
            {"product_id": "LIVE-P3", "product_name": "Ultra-Wide 4K Monitor", "category": "Monitors", "price": 599.99},
            {"product_id": "LIVE-P4", "name": "Ergonomic Mesh Chair", "category": "Furniture", "price": 349.99},
        ])
        storage.write_file(proc_path, sample_df.to_csv(index=False).encode("utf-8"))
        print(f"Successfully wrote 4 sample products to '{proc_path}'")

        # Step 7: Call GET /v1/catalog/summary -> verify auto-seeding
        print(f"\n[7] Calling GET /v1/catalog/summary to trigger auto-seeding...")
        status, summary_resp = http_json("GET", f"{base_url}/v1/catalog/summary", headers=auth_headers)
        print(f"GET /v1/catalog/summary -> HTTP {status}")
        print(f"Summary response: {summary_resp}")
        assert status == 200, f"Summary failed: {summary_resp}"
        assert summary_resp["active"] == 4, f"Expected 4 active seeded products, got {summary_resp['active']}"
        cat_file = f"data/catalog/{tenant_id}/catalog.csv"
        assert storage.exists(cat_file), f"Expected '{cat_file}' to exist after seeding"
        print(f"Verified: '{cat_file}' auto-created and seeded with 4 active items.")

        # Step 8: Exercise CRUD (Add, Edit, Archive, Restore)
        print(f"\n[8] Exercising CRUD Lifecycle...")
        # 8a: Add product
        new_prod = {
            "product_id": "LIVE-P5",
            "product_name": "USB-C Multiport Dock",
            "category": "Accessories",
            "brand": "HyperLink",
            "price": 79.99,
            "in_stock": 1,
            "description": "10-in-1 Aluminum USB-C Hub",
            "custom_ports": "10",
        }
        status, add_resp = http_json("POST", f"{base_url}/v1/catalog/products", new_prod, headers=auth_headers)
        print(f"POST /v1/catalog/products -> HTTP {status} (Product: {add_resp.get('product_id')})")
        assert status == 201

        # 8b: Edit product
        patch_payload = {"price": 69.99, "brand": "HyperLink Pro"}
        status, patch_resp = http_json("PATCH", f"{base_url}/v1/catalog/products/LIVE-P5", patch_payload, headers=auth_headers)
        print(f"PATCH /v1/catalog/products/LIVE-P5 -> HTTP {status} (New Price: {patch_resp.get('price')})")
        assert status == 200
        assert patch_resp["price"] == 69.99
        assert patch_resp["brand"] == "HyperLink Pro"

        # 8c: Archive product
        status, arch_resp = http_json("DELETE", f"{base_url}/v1/catalog/products/LIVE-P5", headers=auth_headers)
        print(f"DELETE /v1/catalog/products/LIVE-P5 -> HTTP {status} (Status: {arch_resp.get('status')})")
        assert status == 200
        assert arch_resp["status"] == "archived"

        # 8d: Restore product
        status, rest_resp = http_json("POST", f"{base_url}/v1/catalog/products/LIVE-P5/restore", headers=auth_headers)
        print(f"POST /v1/catalog/products/LIVE-P5/restore -> HTTP {status} (Status: {rest_resp.get('status')})")
        assert status == 200
        assert rest_resp["status"] == "active"

        # Step 9: Exercise Template, Upload Preview & Commit
        print(f"\n[9] Exercising Template & Multipart Upload Preview/Commit...")
        # 9a: Get template
        status, template_body = http_json("GET", f"{base_url}/v1/catalog/template?format=csv", headers=auth_headers)
        print(f"GET /v1/catalog/template?format=csv -> HTTP {status}")
        assert status == 200
        assert "product_id,product_name,category" in str(template_body)

        # 9b: Preview Upload in upsert mode
        upload_csv = (
            "product_id,product_name,category,brand,price,in_stock\n"
            "LIVE-P5,USB-C Multiport Dock Updated,Accessories,HyperLink,64.99,1\n"
            "LIVE-P6,Noise-Cancelling Studio Earbuds,Audio,SoundPro,99.99,1\n"
        )
        status, preview_resp = http_multipart(
            url=f"{base_url}/v1/catalog/upload",
            files={"file": ("live_catalog_upload.csv", upload_csv.encode("utf-8"), "text/csv")},
            data={"mode": "upsert"},
            headers=auth_headers,
        )
        print(f"POST /v1/catalog/upload (preview) -> HTTP {status}")
        print(f"Preview diff: to_add={preview_resp.get('to_add')}, to_update={preview_resp.get('to_update')}, errors={preview_resp.get('errors')}")
        assert status == 200
        assert preview_resp["to_add"] == 1
        assert preview_resp["to_update"] == 1
        upload_id = preview_resp["upload_id"]

        # 9c: Commit Upload
        status, commit_resp = http_json("POST", f"{base_url}/v1/catalog/upload/{upload_id}/commit", headers=auth_headers)
        print(f"POST /v1/catalog/upload/{upload_id}/commit -> HTTP {status}")
        print(f"Commit response: {commit_resp}")
        assert status == 200
        assert commit_resp["status"] == "committed"
        assert commit_resp["added"] == 1
        assert commit_resp["updated"] == 1

        # Step 10: Exercise History and Snapshot Undo
        print(f"\n[10] Exercising Audit History and Snapshot Undo...")
        # 10a: History
        status, history_resp = http_json("GET", f"{base_url}/v1/catalog/history", headers=auth_headers)
        print(f"GET /v1/catalog/history -> HTTP {status}")
        changes = history_resp.get("changes", [])
        print(f"Retrieved {len(changes)} audit changes. Most recent action: '{changes[0].get('action')}' by '{changes[0].get('who')}'")
        assert status == 200
        assert len(changes) >= 5
        assert changes[0]["action"] == "upload_commit"

        # 10b: Undo
        status, undo_resp = http_json("POST", f"{base_url}/v1/catalog/undo", headers=auth_headers)
        print(f"POST /v1/catalog/undo -> HTTP {status}")
        print(f"Undo response: {undo_resp}")
        assert status == 200
        assert undo_resp["status"] == "restored"

        # Verify summary after undo (P6 should be gone, back to 5 items)
        status, sum_after_undo = http_json("GET", f"{base_url}/v1/catalog/summary", headers=auth_headers)
        assert sum_after_undo["active"] == 5
        print(f"Summary after undo: active={sum_after_undo['active']}, archived={sum_after_undo['archived']}")

        print("\n" + "=" * 70)
        print("ALL LIVE VERIFICATION CHECKS PASSED SUCCESSFULLY!")
        print("=" * 70)
        print(f"\n>>> THROWAWAY TEST TENANT ID: {tenant_id} <<<")
        print(f">>> Company Name: {company_name}")
        print(f">>> Account ID: {account_id}")
        print("=" * 70)

    finally:
        if server_process is not None:
            print("\nStopping uvicorn server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
            print("Server stopped cleanly.")


if __name__ == "__main__":
    main()

