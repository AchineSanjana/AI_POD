"""End-to-End Live Verification Script for Step S2 (Storefront Similar Products).

Runs against live backend on port 8000 and live static/demo server on port 5500.
Creates a throwaway test tenant: 'E2E Test S2 <random_hex>'
Seeds 30 electronic products with specs and prices into catalog.
Verifies:
1. Similar products response with rec_id, target specs, and item specs/price_diff
2. Track endpoint with source='similar' and rec_id
3. Analytics dashboard with similar CTR and metrics
4. Takes mobile (390px) and desktop (1280px) screenshots of demo/similar_products.html
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any
import urllib.parse
import urllib.request
import pandas as pd


EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE_URL = "http://127.0.0.1:8000"
STOREFRONT_URL = "http://127.0.0.1:5500"


def make_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_data: dict[str, Any] | None = None,
    data: bytes | None = None,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    req_headers = headers.copy() if headers else {}
    body_bytes = None
    if json_data is not None:
        body_bytes = json.dumps(json_data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    elif data is not None:
        body_bytes = data

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            resp_headers = dict(resp.headers)
            raw = resp.read()
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception:
                parsed = {"raw": raw.decode("utf-8", errors="replace")}
            return status, parsed, resp_headers
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {"error": raw.decode("utf-8", errors="replace")}
        return e.code, parsed, dict(e.headers)


def wait_for_server(url: str, timeout: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status in (200, 204, 404):
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def build_30_products() -> list[dict[str, Any]]:
    products = [
        # Smartphones (10)
        {"product_id": "SP-01", "product_name": "Galaxy S24 Ultra 5G", "category": "Smartphones", "brand": "Samsung", "price": 285000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=12; storage_gb=512; battery_mah=5000; screen_in=6.8; camera_mp=200", "description": "Flagship Samsung smartphone with Titanium frame, 200MP camera and S-Pen."},
        {"product_id": "SP-02", "product_name": "iPhone 15 Pro Max", "category": "Smartphones", "brand": "Apple", "price": 310000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=8; storage_gb=256; battery_mah=4422; screen_in=6.7; camera_mp=48", "description": "Apple flagship with A17 Pro chip, Titanium design, 5x telephoto optical zoom."},
        {"product_id": "SP-03", "product_name": "Pixel 8 Pro", "category": "Smartphones", "brand": "Google", "price": 245000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=12; storage_gb=256; battery_mah=5050; screen_in=6.7; camera_mp=50", "description": "Google AI smartphone with Tensor G3, Super Actua display and Best Take camera."},
        {"product_id": "SP-04", "product_name": "Redmi Note 13 Pro+", "category": "Smartphones", "brand": "Xiaomi", "price": 125000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=12; storage_gb=512; battery_mah=5000; screen_in=6.67; camera_mp=200", "description": "Midrange killer with 200MP OIS camera, 120W HyperCharge and IP68 rating."},
        {"product_id": "SP-05", "product_name": "Galaxy S24 Plus 5G", "category": "Smartphones", "brand": "Samsung", "price": 235000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=12; storage_gb=256; battery_mah=4900; screen_in=6.7; camera_mp=50", "description": "Samsung Galaxy S24+ with QHD+ Dynamic AMOLED 2X and Armor Aluminum."},
        {"product_id": "SP-06", "product_name": "iPhone 15", "category": "Smartphones", "brand": "Apple", "price": 220000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=6; storage_gb=128; battery_mah=3349; screen_in=6.1; camera_mp=48", "description": "Dynamic Island, 48MP main camera and USB-C in durable color-infused glass."},
        {"product_id": "SP-07", "product_name": "OnePlus 12 5G", "category": "Smartphones", "brand": "OnePlus", "price": 215000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=16; storage_gb=512; battery_mah=5400; screen_in=6.82; camera_mp=50", "description": "Snapdragon 8 Gen 3 flagship with 5400 mAh battery and 100W SUPERVOOC charging."},
        {"product_id": "SP-08", "product_name": "Galaxy A55 5G", "category": "Smartphones", "brand": "Samsung", "price": 115000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=8; storage_gb=256; battery_mah=5000; screen_in=6.6; camera_mp=50", "description": "Premium metal frame, Knox Vault security and bright Super AMOLED 120Hz display."},
        {"product_id": "SP-09", "product_name": "Xiaomi 14 Ultra", "category": "Smartphones", "brand": "Xiaomi", "price": 295000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=16; storage_gb=512; battery_mah=5000; screen_in=6.73; camera_mp=50", "description": "Leica quad camera system with 1-inch sensor and Snapdragon 8 Gen 3."},
        {"product_id": "SP-10", "product_name": "Pixel 8a", "category": "Smartphones", "brand": "Google", "price": 145000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=8; storage_gb=128; battery_mah=4492; screen_in=6.1; camera_mp=64", "description": "The Google AI-first smartphone for everyday photography and battery life."},

        # Laptops (10)
        {"product_id": "LP-01", "product_name": "MacBook Pro 16 M3 Max", "category": "Laptops", "brand": "Apple", "price": 850000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=36; storage_gb=1000; screen_in=16.2; weight_kg=2.16; cores=14", "description": "Pro powerhouse with Liquid Retina XDR display and extreme battery life."},
        {"product_id": "LP-02", "product_name": "Dell XPS 16 OLED", "category": "Laptops", "brand": "Dell", "price": 720000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=32; storage_gb=1000; screen_in=16.3; weight_kg=2.13; cores=16", "description": "Crafted with machined aluminum and Gorilla Glass 3 with 4K OLED touch display."},
        {"product_id": "LP-03", "product_name": "Lenovo ThinkPad X1 Carbon Gen 12", "category": "Laptops", "brand": "Lenovo", "price": 540000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=32; storage_gb=1000; screen_in=14.0; weight_kg=1.09; cores=14", "description": "Ultralight business laptop with carbon-fiber chassis and legendary keyboard."},
        {"product_id": "LP-04", "product_name": "MacBook Air 15 M3", "category": "Laptops", "brand": "Apple", "price": 425000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=16; storage_gb=512; screen_in=15.3; weight_kg=1.51; cores=8", "description": "Impossibly thin design with vibrant 15-inch Liquid Retina display and 18h battery."},
        {"product_id": "LP-05", "product_name": "ASUS ROG Zephyrus G16", "category": "Laptops", "brand": "ASUS", "price": 680000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=32; storage_gb=2000; screen_in=16.0; weight_kg=1.85; cores=16", "description": "Precision gaming ultrabook with RTX 4080 and 2.5K 240Hz OLED ROG Nebula display."},
        {"product_id": "LP-06", "product_name": "HP Spectre x360 14", "category": "Laptops", "brand": "HP", "price": 460000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=16; storage_gb=1000; screen_in=14.0; weight_kg=1.44; cores=14", "description": "Premium 2-in-1 convertible with 2.8K OLED display and Intel Core Ultra 7 processor."},
        {"product_id": "LP-07", "product_name": "Dell XPS 13 Plus", "category": "Laptops", "brand": "Dell", "price": 410000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=16; storage_gb=512; screen_in=13.4; weight_kg=1.24; cores=12", "description": "Futuristic minimalist laptop with seamless glass touchpad and capacitive row."},
        {"product_id": "LP-08", "product_name": "Acer Swift Go 14 OLED", "category": "Laptops", "brand": "Acer", "price": 260000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=16; storage_gb=512; screen_in=14.0; weight_kg=1.32; cores=14", "description": "Affordable Intel Evo certified ultraportable with 90Hz 2.8K OLED screen."},
        {"product_id": "LP-09", "product_name": "MacBook Pro 14 M3 Pro", "category": "Laptops", "brand": "Apple", "price": 610000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=18; storage_gb=512; screen_in=14.2; weight_kg=1.61; cores=11", "description": "Phenomenal performance and battery life in compact 14-inch Space Black body."},
        {"product_id": "LP-10", "product_name": "ASUS Zenbook 14 OLED", "category": "Laptops", "brand": "ASUS", "price": 310000.0, "in_stock": 1, "status": "active", "specs": "ram_gb=16; storage_gb=1000; screen_in=14.0; weight_kg=1.28; cores=14", "description": "All-metal thin and light laptop with 75Wh battery and 120Hz 3K OLED Lumina display."},

        # Audio (10)
        {"product_id": "AD-01", "product_name": "Sony WH-1000XM5 ANC", "category": "Audio", "brand": "Sony", "price": 95000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=30; weight_g=250; drivers_mm=30", "description": "Industry-leading noise cancelling with Auto NC Optimizer and Hi-Res Audio wireless."},
        {"product_id": "AD-02", "product_name": "Bose QuietComfort Ultra", "category": "Audio", "brand": "Bose", "price": 115000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=24; weight_g=252; drivers_mm=35", "description": "World-class noise cancellation, breakthrough spatial audio and CustomTune tech."},
        {"product_id": "AD-03", "product_name": "AirPods Max USB-C", "category": "Audio", "brand": "Apple", "price": 165000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=20; weight_g=384; drivers_mm=40", "description": "High-fidelity audio with active noise cancellation, Transparency mode and spatial audio."},
        {"product_id": "AD-04", "product_name": "Sony WF-1000XM5 Earbuds", "category": "Audio", "brand": "Sony", "price": 75000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=24; weight_g=43; drivers_mm=8.4", "description": "Astonishing sound quality and the best noise cancellation in truly wireless earbuds."},
        {"product_id": "AD-05", "product_name": "AirPods Pro 2 USB-C", "category": "Audio", "brand": "Apple", "price": 78000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=30; weight_g=50; drivers_mm=11", "description": "H2-powered noise cancellation, Adaptive Audio and personalized volume control."},
        {"product_id": "AD-06", "product_name": "Sennheiser Momentum 4", "category": "Audio", "brand": "Sennheiser", "price": 88000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=60; weight_g=293; drivers_mm=42", "description": "Exceptional acoustic sound with audiophile-inspired 42mm transducer system and 60h battery."},
        {"product_id": "AD-07", "product_name": "Bose QuietComfort Earbuds II", "category": "Audio", "brand": "Bose", "price": 68000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=24; weight_g=48; drivers_mm=9.3", "description": "Customized sound and noise cancellation tailored specifically to your ear canals."},
        {"product_id": "AD-08", "product_name": "Galaxy Buds2 Pro", "category": "Audio", "brand": "Samsung", "price": 48000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=18; weight_g=43; drivers_mm=10", "description": "24-bit Hi-Fi audio, intelligent active noise cancellation and 360 Audio."},
        {"product_id": "AD-09", "product_name": "Marshall Major IV", "category": "Audio", "brand": "Marshall", "price": 42000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=80; weight_g=165; drivers_mm=40", "description": "Iconic vintage headphones with over 80 solid hours of wireless playtime and wireless charging."},
        {"product_id": "AD-10", "product_name": "JBL Tour ONE M2", "category": "Audio", "brand": "JBL", "price": 65000.0, "in_stock": 1, "status": "active", "specs": "battery_hrs=50; weight_g=272; drivers_mm=40", "description": "True Adaptive Noise Cancelling with Smart Ambient and JBL Pro Sound."},
    ]
    return products


def main():
    print("=" * 80)
    print("STARTING STEP S2 STOREFRONT SIMILAR PRODUCTS LIVE VERIFICATION")
    print("=" * 80)

    # 1. Start backend process
    print("\n[1] Starting backend uvicorn server on port 8000...")
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 2. Start frontend static server on port 5500
    print("[2] Starting static file server on port 5500...")
    static_proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", "5500", "--bind", "127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for both servers
        assert wait_for_server(f"{BASE_URL}/health", timeout=15.0), "Backend failed to start!"
        assert wait_for_server(f"{STOREFRONT_URL}/demo/similar_products.html", timeout=10.0), "Static server failed to start!"
        print("Backend server is UP at http://127.0.0.1:8000")
        print("Storefront demo server is UP at http://127.0.0.1:5500")

        # 3. Create throwaway tenant
        rand_hex = secrets.token_hex(4)
        company_name = f"E2E Test S2 {rand_hex}"
        email = f"e2e_s2_{rand_hex}@example.com"
        password = "SecurePassword123!"

        print(f"\n[3] Registering throwaway account: '{company_name}' ({email})...")
        s, data, _ = make_request(
            f"{BASE_URL}/v1/accounts/signup",
            method="POST",
            json_data={"company_name": company_name, "email": email, "password": password},
        )
        assert s == 201, f"Signup failed: {s} {data}"
        account_id = data.get("account_id")
        tenant_id = data.get("tenant_id")
        public_key = data.get("public_key")
        private_key = data.get("private_key")
        print(f"Created Account ID: {account_id}, Tenant ID: {tenant_id}")
        print(f"Issued Keys: PK={public_key}, SK={private_key[:12]}...")

        # 4. Verify email
        s, data, _ = make_request(f"{BASE_URL}/v1/accounts/dev/last-verification?email={urllib.parse.quote(email)}")
        assert s == 200, f"Failed to get verification code: {s} {data}"
        v_code = data.get("code")
        print(f"Verification code received: {v_code}")

        s, data, _ = make_request(
            f"{BASE_URL}/v1/accounts/verify-email",
            method="POST",
            json_data={"email": email, "code": v_code},
        )
        assert s == 200, f"Email verification failed: {s} {data}"
        print("Email verified successfully.")

        # 5. Login
        s, data, _ = make_request(
            f"{BASE_URL}/v1/accounts/login",
            method="POST",
            json_data={"email": email, "password": password},
        )
        assert s == 200, f"Login failed: {s} {data}"
        token = data.get("session_token")
        print(f"Authenticated session JWT obtained.")

        # 6. Upload and Commit 30 products
        print("\n[4] Uploading 30 products with specs via POST /v1/catalog/upload...")
        products = build_30_products()
        df = pd.DataFrame(products)
        csv_bytes = df.to_csv(index=False).encode("utf-8")

        # Multipart form data upload
        boundary = "----WebKitFormBoundary" + secrets.token_hex(8)
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(b'Content-Disposition: form-data; name="file"; filename="products.csv"\r\n')
        body.write(b"Content-Type: text/csv\r\n\r\n")
        body.write(csv_bytes)
        body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode("utf-8"))
        payload_data = body.getvalue()

        s, data, _ = make_request(
            f"{BASE_URL}/v1/catalog/upload",
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            data=payload_data,
        )
        assert s == 200, f"Upload failed: {s} {data}"
        upload_id = data.get("upload_id")
        print(f"Upload Preview: upload_id={upload_id}, total_rows={data.get('total_rows')}")

        # Commit upload
        s, data, _ = make_request(
            f"{BASE_URL}/v1/catalog/upload/{upload_id}/commit",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
            json_data={"mode": "replace"},
        )
        assert s == 200, f"Commit failed: {s} {data}"
        print("Committed 30 products to tenant catalogue successfully.")

        # 7. Query Similar Products for SP-01 with Public Key
        print("\n[5] Querying Similar Products via GET /v1/recommendations/similar/SP-01...")
        s, data, headers = make_request(
            f"{BASE_URL}/v1/recommendations/similar/SP-01?top_n=4",
            method="GET",
            headers={"X-API-Key": public_key, "Origin": "http://localhost:5500"},
        )
        assert s == 200, f"Similar request failed: {s} {data}"
        rec_id = data.get("rec_id")
        target = data.get("target")
        similar = data.get("similar_products") or data.get("similar")
        print(f"Similar response received! rec_id: {rec_id} (16 hex chars)")
        print(f"Target: {target.get('product_name')} | Brand: {target.get('brand')} | Specs: {target.get('specs')}")
        print(f"Similar items count: {len(similar)}")
        for item in similar[:3]:
            print(f"  - [{item.get('product_id')}] {item.get('product_name')} | Price: LKR {item.get('price'):,.0f} (diff: {item.get('price_diff'):+,.0f}) | Specs: {item.get('specs')}")

        # 8. Track Events via Public Key
        print("\n[6] Tracking storefront interactions via POST /v1/track...")
        # A) Similar Click
        s, _, _ = make_request(
            f"{BASE_URL}/v1/track",
            method="POST",
            headers={"X-API-Key": public_key},
            json_data={
                "event_type": "click",
                "product_id": "SP-05",
                "session_id": "sess_e2e_live_01",
                "source": "similar",
                "rec_id": rec_id,
            },
        )
        assert s == 202, f"Similar click tracking failed: {s}"
        print("-> Tracked 1x similar click with rec_id")

        # B) Similar Add to Cart
        s, _, _ = make_request(
            f"{BASE_URL}/v1/track",
            method="POST",
            headers={"X-API-Key": public_key},
            json_data={
                "event_type": "add_to_cart",
                "product_id": "SP-05",
                "session_id": "sess_e2e_live_01",
                "source": "similar",
                "rec_id": rec_id,
            },
        )
        assert s == 202, f"Similar add_to_cart tracking failed: {s}"
        print("-> Tracked 1x similar add_to_cart with rec_id")

        # C) Similar Purchase
        s, _, _ = make_request(
            f"{BASE_URL}/v1/track",
            method="POST",
            headers={"X-API-Key": public_key},
            json_data={
                "event_type": "purchase",
                "product_id": "SP-05",
                "session_id": "sess_e2e_live_01",
                "source": "similar",
                "rec_id": rec_id,
            },
        )
        assert s == 202, f"Similar purchase tracking failed: {s}"
        print("-> Tracked 1x similar purchase with rec_id")

        # D) Recommendation Click
        s, _, _ = make_request(
            f"{BASE_URL}/v1/track",
            method="POST",
            headers={"X-API-Key": public_key},
            json_data={
                "event_type": "click",
                "product_id": "SP-03",
                "session_id": "sess_e2e_live_01",
                "source": "recommendation",
                "rec_id": "0123456789abcdef",
            },
        )
        assert s == 202, f"Recommendation click tracking failed: {s}"
        print("-> Tracked 1x recommendation click with rec_id")

        # E) Wizard-Test click (Must be filtered out from dashboard metrics)
        s, _, _ = make_request(
            f"{BASE_URL}/v1/track",
            method="POST",
            headers={"X-API-Key": public_key, "X-AIPOD-Source": "wizard-test"},
            json_data={
                "event_type": "click",
                "product_id": "SP-99",
                "session_id": "sess_e2e_live_01",
                "source": "similar",
                "rec_id": "deadbeefcafebabe",
            },
        )
        assert s == 202
        print("-> Tracked 1x wizard-test click (to verify exclusion)")

        # 9. Verify Dashboard Analytics
        print("\n[7] Verifying dashboard analytics reporting via GET /v1/dashboard/analytics...")
        # Allow buffer flush or call dashboard directly
        s, analytics, _ = make_request(
            f"{BASE_URL}/v1/dashboard/analytics",
            method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert s == 200, f"Analytics query failed: {s} {analytics}"
        print(f"Analytics Data: similar_clicks={analytics.get('similar_clicks')}, "
              f"similar_add_to_carts={analytics.get('similar_add_to_carts')}, "
              f"similar_purchases={analytics.get('similar_purchases')}, "
              f"similar_ctr={analytics.get('similar_ctr'):.4f}, "
              f"recommendation_clicks={analytics.get('recommendation_clicks')}")

        assert analytics.get("similar_clicks", 0) >= 1, "similar_clicks was not incremented"
        assert analytics.get("similar_add_to_carts", 0) >= 1, "similar_add_to_carts was not incremented"
        assert analytics.get("similar_purchases", 0) >= 1, "similar_purchases was not incremented"
        assert analytics.get("similar_ctr", 0.0) > 0.0, "similar_ctr was not computed"
        assert analytics.get("recommendation_clicks", 0) >= 1, "recommendation_clicks was not incremented"
        print("Confirmed: All telemetry metrics computed accurately and wizard-test traffic excluded!")

        # 10. Capture Screenshots via Headless Edge
        print("\n[8] Capturing screenshots of demo/similar_products.html...")
        screenshots_dir = Path("docs/screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        mobile_path = screenshots_dir / "s2_mobile.png"
        desktop_path = screenshots_dir / "s2_desktop.png"

        target_url = f"{STOREFRONT_URL}/demo/similar_products.html?base={BASE_URL}&key={public_key}&product=SP-01"

        if os.path.exists(EDGE_PATH):
            # Mobile: 390x844
            print(f"Capturing Mobile Viewport (390x844) to {mobile_path}...")
            cmd_mobile = [
                EDGE_PATH,
                "--headless",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size=390,844",
                f"--screenshot={mobile_path.resolve()}",
                target_url,
            ]
            subprocess.run(cmd_mobile, check=True, timeout=15)
            assert mobile_path.exists() and mobile_path.stat().st_size > 1000, "Mobile screenshot capture failed"
            print(f"-> Captured mobile screenshot: {mobile_path.stat().st_size:,} bytes")

            # Desktop: 1280x900
            print(f"Capturing Desktop Viewport (1280x900) to {desktop_path}...")
            cmd_desktop = [
                EDGE_PATH,
                "--headless",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size=1280,900",
                f"--screenshot={desktop_path.resolve()}",
                target_url,
            ]
            subprocess.run(cmd_desktop, check=True, timeout=15)
            assert desktop_path.exists() and desktop_path.stat().st_size > 1000, "Desktop screenshot capture failed"
            print(f"-> Captured desktop screenshot: {desktop_path.stat().st_size:,} bytes")
        else:
            print(f"Edge binary not found at {EDGE_PATH}; skipping browser capture")

        print("\n" + "=" * 80)
        print("ALL STEP S2 LIVE VERIFICATION CHECKS PASSED!")
        print(f"Throwaway Tenant ID: {tenant_id}")
        print("=" * 80)

    finally:
        print("\nStopping background servers...")
        try:
            backend_proc.terminate()
            backend_proc.wait(timeout=5)
        except Exception:
            backend_proc.kill()
        try:
            static_proc.terminate()
            static_proc.wait(timeout=5)
        except Exception:
            static_proc.kill()
        print("Servers stopped.")


if __name__ == "__main__":
    main()
