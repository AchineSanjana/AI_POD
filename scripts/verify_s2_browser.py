#!/usr/bin/env python3
"""scripts/verify_s2_browser.py

Playwright + Chromium automated browser verification script for Step S2:
Storefront Similar Products & SDK Integration.

Verifies:
1. Status pill says Connected (or Connected (pk-...))
2. At least 3 .aipod-sim-card elements are visible
3. Compare table exists with at least 2 product columns
4. document.documentElement.scrollWidth <= window.innerWidth across viewports:
   - 390x844 (Mobile iPhone 12/13/14)
   - 360x800 (Mobile Android standard)
   - 1280x900 (Desktop)
   Only carousel and compare table may scroll horizontally in their own overflow containers.
5. Zero unhandled console errors or runtime exceptions.
6. Clicking a card sends POST /v1/track with source="similar" and a hex rec_id.
7. Telemetry flush reflects similar_clicks >= 1 in GET /v1/dashboard/analytics.
8. Malicious product name (<img src=x onerror=alert(1)>) renders as text, no alert dialog executed.

Saves full-page screenshots:
- docs/screenshots/s2_mobile_full.png (390 px)
- docs/screenshots/s2_mobile.png (overwritten)
- docs/screenshots/s2_desktop_full.png (1280 px)
- docs/screenshots/s2_compare_mobile.png (390 px with compare view)
"""

import argparse
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "docs" / "screenshots"


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_http(url: str, timeout: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status in (200, 204):
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def http_post_json(url: str, data: dict, headers: dict | None = None) -> tuple[int, dict]:
    payload = json.dumps(data).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=payload, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8"))
        return e.code, body


def http_get_json(url: str, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8"))
        return e.code, body


def build_30_product_catalog() -> list[dict]:
    products = []
    # 10 Smartphones
    smartphones = [
        ("SP-01", "Galaxy S24 Ultra 5G", "Samsung", 285000.0, "ram_gb=12; storage_gb=512; battery_mah=5000; screen_in=6.8; camera_mp=200", "Flagship Samsung smartphone with Titanium frame"),
        ("SP-02", "iPhone 15 Pro Max", "Apple", 310000.0, "ram_gb=8; storage_gb=256; battery_mah=4422; screen_in=6.7; camera_mp=48", "Apple flagship with A17 Pro chip"),
        ("SP-03", "Pixel 8 Pro", "Google", 245000.0, "ram_gb=12; storage_gb=256; battery_mah=5050; screen_in=6.7; camera_mp=50", "Google AI smartphone with Tensor G3"),
        ("SP-04", "Redmi Note 13 Pro+", "Xiaomi", 125000.0, "ram_gb=12; storage_gb=512; battery_mah=5000; screen_in=6.67; camera_mp=200", "Midrange killer with 200MP OIS"),
        ("SP-05", "Galaxy S24 Plus 5G", "Samsung", 235000.0, "ram_gb=12; storage_gb=256; battery_mah=4900; screen_in=6.7; camera_mp=50", "Samsung Galaxy S24+ with QHD+ Dynamic AMOLED"),
        ("SP-06", "iPhone 15", "Apple", 220000.0, "ram_gb=6; storage_gb=128; battery_mah=3349; screen_in=6.1; camera_mp=48", "Dynamic Island, 48MP main camera"),
        ("SP-07", "OnePlus 12 5G", "OnePlus", 215000.0, "ram_gb=16; storage_gb=512; battery_mah=5400; screen_in=6.82; camera_mp=50", "Snapdragon 8 Gen 3 flagship"),
        ("SP-08", "Galaxy A55 5G", "Samsung", 115000.0, "ram_gb=8; storage_gb=256; battery_mah=5000; screen_in=6.6; camera_mp=50", "Premium metal frame and Knox Vault"),
        ("SP-09", "Xiaomi 14 Ultra", "Xiaomi", 295000.0, "ram_gb=16; storage_gb=512; battery_mah=5000; screen_in=6.73; camera_mp=50", "Leica quad camera system with 1-inch sensor"),
        # XSS test payload product
        ("SP-10", "<img src=x onerror=alert(1)>", "SecurityProbe", 199000.0, "ram_gb=12; storage_gb=256; battery_mah=4800; screen_in=6.5; camera_mp=64", "Security testing payload product name"),
    ]
    for pid, name, brand, price, specs, desc in smartphones:
        products.append({
            "product_id": pid,
            "product_name": name,
            "category": "Smartphones",
            "status": "active",
            "brand": brand,
            "price": price,
            "in_stock": 1,
            "description": desc,
            "specs": specs,
            "image_url": "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=300",
        })

    # 10 Laptops
    for i in range(1, 11):
        products.append({
            "product_id": f"LP-{i:02d}",
            "product_name": f"Pro Laptop Book {i}",
            "category": "Laptops",
            "status": "active",
            "brand": "Apple" if i % 2 == 0 else "Dell",
            "price": 350000.0 + (i * 15000),
            "in_stock": 1,
            "description": f"High performance ultrabook workstation {i}",
            "specs": f"ram_gb={(16 if i % 2 == 0 else 32)}; storage_gb=1024; screen_in=15.6; weight_kg=1.4",
            "image_url": "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=300",
        })

    # 10 Accessories
    for i in range(1, 11):
        products.append({
            "product_id": f"AD-{i:02d}",
            "product_name": f"Wireless Audio Pods {i}",
            "category": "Accessories",
            "status": "active",
            "brand": "Sony" if i % 2 == 0 else "Bose",
            "price": 45000.0 + (i * 3000),
            "in_stock": 1,
            "description": f"Active noise cancelling wireless earbuds {i}",
            "specs": f"battery_mah=500; bluetooth_ver=5.3; weight_g=45",
            "image_url": "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=300",
        })

    return products


def seed_tenant_catalog(base_url: str) -> tuple[str, str, str]:
    """Create a fresh throwaway tenant and upload a 30-product catalog."""
    suffix = uuid.uuid4().hex[:8]
    email = f"e2e_s2_browser_{suffix}@example.com"
    company_name = f"e2e_tenant_{suffix}"
    signup_url = f"{base_url}/v1/accounts/signup"

    status, resp = http_post_json(signup_url, {
        "company_name": company_name,
        "email": email,
        "password": "Password123!",
    })
    if status not in (200, 201):
        raise RuntimeError(f"Signup failed ({status}): {resp}")

    tenant_id = resp["tenant_id"]
    api_key = resp.get("private_key") or resp.get("api_key")
    public_key = resp["public_key"]

    # Build CSV and save directly to storage path for immediate availability
    catalog_dir = PROJECT_ROOT / "data" / "catalog" / tenant_id
    catalog_dir.mkdir(parents=True, exist_ok=True)
    csv_path = catalog_dir / "catalog.csv"

    products = build_30_product_catalog()
    fieldnames = ["product_id", "product_name", "category", "status", "brand", "price", "in_stock", "description", "specs", "image_url"]

    import csv
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in products:
            writer.writerow(p)

    return tenant_id, api_key, public_key


def run_browser_verification(base_url: str = "http://127.0.0.1:8000", demo_url: str = "http://127.0.0.1:5500", headless: bool = True):
    from playwright.sync_api import sync_playwright

    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("STEP S2 PLAYWRIGHT + CHROMIUM BROWSER VERIFICATION")
    print("=" * 70)

    # 1. Seed throwaway tenant
    print("[1/5] Seeding throwaway tenant and 30-product catalog...")
    tenant_id, api_key, public_key = seed_tenant_catalog(base_url)
    print(f"      Tenant: {tenant_id}")
    print(f"      Public Key: {public_key}")
    print(f"      Secret Key: {api_key[:10]}...")

    viewports = [
        {"name": "mobile_390", "width": 390, "height": 844, "label": "390x844 (Mobile iPhone)"},
        {"name": "mobile_360", "width": 360, "height": 800, "label": "360x800 (Mobile Android)"},
        {"name": "desktop_1280", "width": 1280, "height": 900, "label": "1280x900 (Desktop)"},
    ]

    results_table = {}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=headless)
        except Exception:
            # Fallback to system Chromium browser
            browser = p.chromium.launch(channel="msedge", headless=headless)

        for vp in viewports:
            vp_name = vp["name"]
            vp_w = vp["width"]
            vp_h = vp["height"]
            print(f"\n[2/5] Running verification for viewport {vp['label']}...")

            context = browser.new_context(
                viewport={"width": vp_w, "height": vp_h},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()

            console_errors = []
            dialogs_opened = []
            intercepted_track_requests = []

            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type in ("error", "assert") else None)
            page.on("pageerror", lambda err: console_errors.append(str(err)))
            page.on("dialog", lambda d: dialogs_opened.append(d.message))

            def on_request(req):
                if "/v1/track" in req.url and req.method == "POST":
                    try:
                        post_data = req.post_data_json or json.loads(req.post_data or "{}")
                        intercepted_track_requests.append(post_data)
                    except Exception:
                        pass

            page.on("request", on_request)

            test_url = f"{demo_url}/similar_products.html?base={base_url}&key={public_key}&product=SP-01"
            print(f"      Navigating to {test_url}")
            page.goto(test_url, wait_until="networkidle")

            # Check (a): Status pill says Connected
            pill_ok = False
            try:
                page.wait_for_selector("#sdk-status-text", timeout=8000)
                status_text = page.locator("#sdk-status-text").inner_text()
                pill_ok = "Connected" in status_text
            except Exception as e:
                status_text = str(e)

            # Check (b): At least 3 .aipod-sim-card elements visible
            cards_ok = False
            card_count = 0
            try:
                page.wait_for_selector(".aipod-sim-card", timeout=8000)
                cards = page.locator(".aipod-sim-card").all()
                card_count = len(cards)
                cards_ok = card_count >= 3
            except Exception:
                pass

            # Check (c): Compare table exists with at least 2 product columns
            compare_ok = False
            col_count = 0
            try:
                page.wait_for_selector(".aipod-sim-compare-table", timeout=8000)
                headers = page.locator(".aipod-sim-compare-table th").all()
                col_count = len(headers)
                compare_ok = col_count >= 3  # Feature col + Target + at least 1-2 similar products
            except Exception:
                pass

            # Check (d): No horizontal page overflow (scrollWidth <= window.innerWidth)
            overflow_info = page.evaluate("""() => {
                const doc = document.documentElement;
                return {
                    scrollWidth: doc.scrollWidth,
                    clientWidth: doc.clientWidth,
                    innerWidth: window.innerWidth
                };
            }""")
            scroll_w = overflow_info["scrollWidth"]
            inner_w = overflow_info["innerWidth"]
            # Allow 1px tolerance for subpixel rounding in browser layout engines
            no_overflow = scroll_w <= (inner_w + 1)

            # Check (e): No console errors
            # Filter out expected transient 404s like /favicon.ico
            real_errors = [e for e in console_errors if "favicon" not in e.lower()]
            if real_errors:
                print(f"      Console errors in {vp_name}: {real_errors}")
            no_errors = len(real_errors) == 0

            # Check (f): Click card triggers POST /v1/track with source="similar" and hex rec_id
            click_tracked = False
            clicked_rec_id = ""
            try:
                first_card = page.locator(".aipod-sim-card").first
                first_card.click()
                # Wait briefly for fetch
                time.sleep(1.0)
                for tr in intercepted_track_requests:
                    if tr.get("source") == "similar" and tr.get("rec_id"):
                        rec_id = str(tr["rec_id"])
                        if re.match(r"^[0-9a-fA-F]{1,32}$", rec_id):
                            click_tracked = True
                            clicked_rec_id = rec_id
                            break
            except Exception as e:
                print(f"      Click tracking exception: {e}")

            # Check (g): Telemetry flush -> GET /v1/dashboard/analytics shows similar_clicks >= 1
            analytics_ok = False
            similar_clicks = 0
            try:
                # Wait for flusher or query analytics
                time.sleep(5.5)
                stat, analytics = http_get_json(f"{base_url}/v1/dashboard/analytics", headers={"X-API-Key": api_key})
                similar_clicks = analytics.get("similar_clicks", 0)
                analytics_ok = stat == 200 and similar_clicks >= 1
            except Exception as e:
                print(f"      Analytics query exception: {e}")

            # Check (h): Malicious product name appears as text and NO dialog/alert executed
            xss_safe = False
            try:
                # Select product SP-10 to view target card with malicious name
                page.goto(f"{demo_url}/similar_products.html?base={base_url}&key={public_key}&product=SP-10", wait_until="networkidle")
                time.sleep(1.0)
                target_name_text = page.locator("#target-name").inner_text()
                # Malicious name should be rendered as plain text, dialog count 0
                xss_safe = ("<img src=x onerror=alert(1)>" in target_name_text or "onerror=alert(1)" in target_name_text) and len(dialogs_opened) == 0
            except Exception as e:
                print(f"      XSS test exception: {e}")

            # Screenshot captures
            if vp_w == 390:
                # Re-load SP-01 for standard screenshots
                page.goto(f"{demo_url}/similar_products.html?base={base_url}&key={public_key}&product=SP-01", wait_until="networkidle")
                page.wait_for_selector(".aipod-sim-card", timeout=8000)
                time.sleep(0.5)

                mobile_full_path = SCREENSHOTS_DIR / "s2_mobile_full.png"
                mobile_old_path = SCREENSHOTS_DIR / "s2_mobile.png"
                page.screenshot(path=str(mobile_full_path), full_page=True)
                page.screenshot(path=str(mobile_old_path), full_page=True)
                print(f"      Saved: {mobile_full_path} and {mobile_old_path}")

                # Compare table view screenshot
                compare_elem = page.locator("#compare-table-container")
                compare_elem.scroll_into_view_if_needed()
                time.sleep(0.5)
                compare_path = SCREENSHOTS_DIR / "s2_compare_mobile.png"
                page.screenshot(path=str(compare_path), full_page=True)
                print(f"      Saved: {compare_path}")

            elif vp_w == 1280:
                desktop_full_path = SCREENSHOTS_DIR / "s2_desktop_full.png"
                page.screenshot(path=str(desktop_full_path), full_page=True)
                print(f"      Saved: {desktop_full_path}")

            results_table[vp_name] = {
                "(a) Status Pill Connected": "PASS" if pill_ok else f"FAIL ({status_text})",
                "(b) >= 3 Similar Cards": f"PASS ({card_count} cards)" if cards_ok else f"FAIL ({card_count})",
                "(c) Compare Table Product Cols": f"PASS ({col_count} headers)" if compare_ok else f"FAIL ({col_count})",
                "(d) scrollWidth <= innerWidth": f"PASS ({scroll_w}px <= {inner_w}px)" if no_overflow else f"FAIL ({scroll_w}px > {inner_w}px)",
                "(e) Zero Console Errors": "PASS" if no_errors else f"FAIL ({len(real_errors)} errors)",
                "(f) Click Sends /v1/track": f"PASS (rec_id: {clicked_rec_id[:8]}...)" if click_tracked else "FAIL",
                "(g) Analytics similar_clicks >= 1": f"PASS (clicks: {similar_clicks})" if analytics_ok else f"FAIL ({similar_clicks})",
                "(h) XSS Safe Text (No Alert)": "PASS (0 dialogs)" if xss_safe else f"FAIL (dialogs: {len(dialogs_opened)})",
            }

            context.close()

        browser.close()

    print("\n" + "=" * 70)
    print("VERIFICATION RESULTS SUMMARY")
    print("=" * 70)
    all_passed = True
    for vp_name, checks in results_table.items():
        print(f"\n[Viewport: {vp_name}]")
        for check, res in checks.items():
            status_tag = "[PASS]" if "PASS" in res else "[FAIL]"
            if "FAIL" in res:
                all_passed = False
            print(f"  {status_tag} {check}: {res}")

    print("=" * 70)
    if all_passed:
        print("ALL REAL BROWSER ASSERTIONS PASSED SUCCESSFULLY!")
    else:
        print("SOME BROWSER ASSERTIONS FAILED - CHECK DETAILS ABOVE.")
    print("=" * 70)
    return all_passed


def run_with_servers(base_url: str = "http://127.0.0.1:8000", demo_url: str = "http://127.0.0.1:5500", headless: bool = True) -> bool:
    api_proc = None
    demo_proc = None

    try:
        # Check if backend is running, otherwise start it
        if not is_port_in_use(8000):
            print("Starting API backend on port 8000...")
            api_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=str(PROJECT_ROOT),
            )
            assert wait_for_http(f"{base_url}/health"), "Failed to start backend on 8000"

        # Check if demo server is running, otherwise start it
        if not is_port_in_use(5500):
            print("Starting Demo HTTP server on port 5500...")
            demo_proc = subprocess.Popen(
                [sys.executable, "-m", "http.server", "5500", "--bind", "127.0.0.1"],
                cwd=str(PROJECT_ROOT / "demo"),
            )
            assert wait_for_http(f"{demo_url}/similar_products.html"), "Failed to start demo server on 5500"

        return run_browser_verification(
            base_url=base_url,
            demo_url=demo_url,
            headless=headless,
        )

    finally:
        if api_proc:
            print("Stopping API backend process...")
            api_proc.terminate()
        if demo_proc:
            print("Stopping demo server process...")
            demo_proc.terminate()


def main():
    parser = argparse.ArgumentParser(description="Step S2 Playwright Browser Verification")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--demo-url", default="http://127.0.0.1:5500", help="Demo HTTP server URL")
    parser.add_argument("--no-headless", action="store_true", help="Run browser in headful mode")
    args = parser.parse_args()

    passed = run_with_servers(
        base_url=args.base_url,
        demo_url=args.demo_url,
        headless=not args.no_headless,
    )
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

