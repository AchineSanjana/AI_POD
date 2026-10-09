#!/usr/bin/env python3
"""Script to verify recommendations endpoint and CORS preflight headers.

Usage:
    python scripts/check_storefront_api.py [base_url] [public_key] [customer_id]

Example:
    python scripts/check_storefront_api.py http://127.0.0.1:8000 pk-fresh_cart_co-375554e8b1aa 2455
    python scripts/check_storefront_api.py http://54.211.10.5:8000 pk-online-retail-xxxx 14911
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def check_api(base_url: str, public_key: str, customer_id: str, origin: str | None = None) -> bool:
    base = base_url.rstrip("/")
    test_origin = origin or base

    print(f"\n{'='*70}")
    print("AI_POD Storefront API Diagnostics")
    print(f"Base URL    : {base}")
    print(f"Public Key  : {public_key[:8]}...{public_key[-4:] if len(public_key) > 12 else ''} ({len(public_key)} chars)")
    print(f"Customer ID : {customer_id}")
    print(f"Test Origin : {test_origin}")
    print(f"{'='*70}\n")

    # -------------------------------------------------------------------------
    # 1. OPTIONS Preflight Request
    # -------------------------------------------------------------------------
    options_url = f"{base}/v1/recommendations"
    print(f"[1/2] Sending OPTIONS preflight to: {options_url}")
    options_req = urllib.request.Request(
        options_url,
        method="OPTIONS",
        headers={
            "Origin": test_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
            "User-Agent": "AI_POD-Diagnostics/1.0",
        },
    )

    try:
        with urllib.request.urlopen(options_req, timeout=10) as resp:
            opt_status = resp.status
            print(f"  --> Status Code: {opt_status} OK")
            print("  --> Key Preflight Response Headers:")
            cors_headers = [
                "access-control-allow-origin",
                "access-control-allow-methods",
                "access-control-allow-headers",
                "access-control-allow-credentials",
            ]
            for h in cors_headers:
                val = resp.headers.get(h)
                print(f"      - {h}: {val}")
    except urllib.error.HTTPError as e:
        print(f"  [!] Preflight returned HTTP Error {e.code}: {e.reason}")
        for k, v in e.headers.items():
            if k.lower().startswith("access-control"):
                print(f"      - {k}: {v}")
    except Exception as e:
        print(f"  [X] Failed to connect for OPTIONS preflight: {e}")
        return False

    # -------------------------------------------------------------------------
    # 2. GET Recommendations Request
    # -------------------------------------------------------------------------
    get_url = f"{base}/v1/recommendations?customer_id={urllib.parse.quote(str(customer_id))}&top_n=5"
    print(f"\n[2/2] Sending GET recommendations to: {get_url}")
    get_req = urllib.request.Request(
        get_url,
        method="GET",
        headers={
            "X-API-Key": public_key,
            "Origin": test_origin,
            "Accept": "application/json",
            "User-Agent": "AI_POD-Diagnostics/1.0",
        },
    )

    try:
        with urllib.request.urlopen(get_req, timeout=10) as resp:
            get_status = resp.status
            content_type = resp.headers.get("content-type", "")
            cors_origin = resp.headers.get("access-control-allow-origin", "not set")
            body_bytes = resp.read()

            print(f"  --> Status Code: {get_status} OK")
            print("  --> Key Response Headers:")
            print(f"      - content-type: {content_type}")
            print(f"      - access-control-allow-origin: {cors_origin}")

            try:
                data = json.loads(body_bytes.decode("utf-8"))
            except Exception as parse_err:
                print(f"  [X] Failed to parse JSON body: {parse_err}")
                print(f"      Raw body: {body_bytes[:200]}")
                return False

            recs = data.get("recommendations", [])
            is_fallback = data.get("fallback", False)
            tenant = data.get("tenant_id", "unknown")
            cust = data.get("customer_id", customer_id)

            print("\n  --> Response Payload Summary:")
            print(f"      - Tenant ID       : {tenant}")
            print(f"      - Customer ID     : {cust}")
            print(f"      - Recommendations : {len(recs)} returned")
            print(f"      - Fallback Flag   : {is_fallback}")

            if recs:
                print("      - Top Product IDs :")
                for r in recs[:5]:
                    pid = r.get("product_id")
                    pname = r.get("product_name") or "N/A"
                    print(f"          * #{r.get('rank', '-')}: {pid} ({pname})")

            print(f"\n{'-'*70}")
            if is_fallback:
                print("VERDICT: Recommendations returned successfully via POPULARITY FALLBACK (fallback: true).")
            else:
                print("VERDICT: Recommendations returned successfully via TRAINED ML MODEL.")
            print(f"{'-'*70}\n")
            return True

    except urllib.error.HTTPError as e:
        print(f"  [X] GET recommendations returned HTTP Error {e.code}: {e.reason}")
        try:
            err_body = e.read().decode("utf-8")
            print(f"      Response body: {err_body}")
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"  [X] Failed to connect for GET recommendations: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="AI_POD Storefront API Diagnostic & Preflight Checker")
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:8000", help="Base URL (e.g. http://192.168.1.50:8000)")
    parser.add_argument("public_key", nargs="?", default="pk-fresh_cart_co-375554e8b1aa", help="Public tenant key (pk-...)")
    parser.add_argument("customer_id", nargs="?", default="2455", help="Customer ID to score (e.g. 2455)")
    parser.add_argument("--origin", dest="origin", default=None, help="Origin header for preflight test")

    args = parser.parse_args()
    success = check_api(args.base_url, args.public_key, args.customer_id, args.origin)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
