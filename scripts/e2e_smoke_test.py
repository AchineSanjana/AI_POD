#!/usr/bin/env python3
"""End-to-End Smoke Test for AI_POD.

Executes a full lifecycle smoke test against a live AI_POD API server:
1. Health check
2. Synthetic transactional dataset generation (in memory, ~300 customers, ~40 products, 3000+ rows)
3. Company signup and security checks
4. Dev verification and session login
5. Onboarding wizard pipeline (upload, validate, confirm, tournament train, poll)
6. Disk artifact assertions (local mode) and model tournament verification
7. Recommendations testing (sample customers, live vs test traffic, cold-start fallback)
8. Telemetry tracking events and dashboard analytics assertions
9. Security & multi-tenant isolation verification
10. API key rotation verification
11. Summary table and credentials output

Usage:
    python scripts/e2e_smoke_test.py [--base-url http://127.0.0.1:8000]
    python scripts/e2e_smoke_test.py --cleanup [--yes]
    python scripts/e2e_smoke_test.py --after-restart <tenant_id> <email> <password> [--base-url http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import random
import secrets
import shutil
import sys
import time
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


class SmokeTestRunner:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.results: list[dict[str, Any]] = []

    def record_step(self, step_num: int, name: str, success: bool, duration: float, detail: str = ""):
        self.results.append({
            "step": step_num,
            "name": name,
            "success": success,
            "duration": duration,
            "detail": detail,
        })
        status = f"{GREEN}PASS{RESET}" if success else f"{RED}FAIL{RESET}"
        print(f"[{status}] Step {step_num:02d}: {name} ({duration:.2f}s)")
        if detail:
            prefix = "      "
            print(f"{prefix}{detail}")
        if not success:
            print(f"\n{RED}ERROR: Smoke test failed at Step {step_num}: {name}{RESET}")
            sys.exit(1)

    # -----------------------------------------------------------------------
    # Step 1: Health check
    # -----------------------------------------------------------------------
    def step_1_health_check(self):
        t0 = time.perf_counter()
        url = f"{self.base_url}/health"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                self.record_step(1, "Health Check GET /health", False, time.perf_counter() - t0, f"Status code {resp.status_code}: {resp.text}")
                return
            data = resp.json()
            if data.get("status") != "ok":
                self.record_step(1, "Health Check GET /health", False, time.perf_counter() - t0, f"Unexpected body: {data}")
                return
            self.record_step(1, "Health Check GET /health", True, time.perf_counter() - t0, "Server responded with status=ok")
        except Exception as exc:
            self.record_step(1, "Health Check GET /health", False, time.perf_counter() - t0, f"Connection failed: {exc}")

    # -----------------------------------------------------------------------
    # Step 2: Synthetic transactional CSV generation
    # -----------------------------------------------------------------------
    def step_2_generate_dataset(self) -> bytes:
        t0 = time.perf_counter()
        num_customers = 300
        num_products = 40
        num_rows = 3500

        customer_ids = [f"CUST_{i:04d}" for i in range(1, num_customers + 1)]
        product_catalog = [
            (f"PROD_{i:03d}", f"Catalog Product {i}")
            for i in range(1, num_products + 1)
        ]

        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["order_id", "customer_id", "product_id", "product_name", "quantity", "timestamp"])

        base_time = datetime.now(timezone.utc) - timedelta(days=25)
        for row_idx in range(1, num_rows + 1):
            cid = random.choice(customer_ids)
            pid, pname = random.choice(product_catalog)
            qty = random.randint(1, 5)
            order_id = f"ORD_{row_idx:06d}"
            ts = (base_time + timedelta(minutes=row_idx * 10)).isoformat()
            writer.writerow([order_id, cid, pid, pname, qty, ts])

        csv_bytes = out.getvalue().encode("utf-8")
        size_kb = len(csv_bytes) / 1024.0
        self.record_step(
            2,
            "Generate Synthetic Transactional CSV",
            True,
            time.perf_counter() - t0,
            f"Generated {num_rows} rows, {num_customers} customers, {num_products} products ({size_kb:.1f} KB)",
        )
        return csv_bytes

    # -----------------------------------------------------------------------
    # Step 3: Company signup
    # -----------------------------------------------------------------------
    def step_3_signup(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        rand_hex = secrets.token_hex(4)
        company_name = f"E2E Test {rand_hex}"
        email = f"e2e_{rand_hex}@example.com"
        password = "TestPassword123!Secure"

        url = f"{self.base_url}/v1/accounts/signup"
        payload = {
            "company_name": company_name,
            "email": email,
            "password": password,
        }
        resp = self.session.post(url, json=payload, timeout=15)
        if resp.status_code not in (200, 201):
            self.record_step(3, "Company Signup", False, time.perf_counter() - t0, f"Status {resp.status_code}: {resp.text}")
            return {}

        data = resp.json()

        # Security check: MUST NOT contain verification code
        forbidden_keys = [k for k in ("verification_code", "code", "token") if k in data]
        if forbidden_keys:
            self.record_step(
                3,
                "Company Signup",
                False,
                time.perf_counter() - t0,
                f"SECURITY LEAK: Response contained secret fields: {forbidden_keys}",
            )
            return {}

        tenant_id = data.get("tenant_id")
        pk = data.get("public_key")
        sk = data.get("private_key")

        if not tenant_id or not pk or not sk:
            self.record_step(3, "Company Signup", False, time.perf_counter() - t0, f"Missing tenant/keys in response: {data}")
            return {}

        self.record_step(
            3,
            "Company Signup",
            True,
            time.perf_counter() - t0,
            f"Tenant: {tenant_id}, Email: {email} (verification code omitted from response as required)",
        )
        return {
            "company_name": company_name,
            "email": email,
            "password": password,
            "tenant_id": tenant_id,
            "pk": pk,
            "sk": sk,
        }

    # -----------------------------------------------------------------------
    # Step 4: Verification and Login
    # -----------------------------------------------------------------------
    def step_4_verify_and_login(self, creds: dict[str, Any]) -> str:
        t0 = time.perf_counter()
        email = creds["email"]
        password = creds["password"]

        # Read dev code
        dev_url = f"{self.base_url}/v1/accounts/dev/last-verification?email={email}"
        dev_resp = self.session.get(dev_url, timeout=10)
        if dev_resp.status_code != 200:
            self.record_step(4, "Verification & Login", False, time.perf_counter() - t0, f"Failed getting dev code: {dev_resp.text}")
            return ""

        code = dev_resp.json().get("code")
        if not code:
            self.record_step(4, "Verification & Login", False, time.perf_counter() - t0, "Dev code missing in response")
            return ""

        # Verify email
        verify_url = f"{self.base_url}/v1/accounts/verify-email"
        v_resp = self.session.post(verify_url, json={"email": email, "code": code}, timeout=10)
        if v_resp.status_code != 200:
            self.record_step(4, "Verification & Login", False, time.perf_counter() - t0, f"Verify email failed: {v_resp.text}")
            return ""

        # Login
        login_url = f"{self.base_url}/v1/accounts/login"
        l_resp = self.session.post(login_url, json={"email": email, "password": password}, timeout=10)
        if l_resp.status_code != 200:
            self.record_step(4, "Verification & Login", False, time.perf_counter() - t0, f"Login failed: {l_resp.text}")
            return ""

        token = (
            l_resp.json().get("session_token")
            or l_resp.json().get("access_token")
            or l_resp.json().get("token")
        )
        if not token:
            self.record_step(4, "Verification & Login", False, time.perf_counter() - t0, "Login response missing JWT token")
            return ""

        self.record_step(
            4,
            "Verification & Login",
            True,
            time.perf_counter() - t0,
            f"Code {code} verified; session JWT issued successfully",
        )
        return token

    # -----------------------------------------------------------------------
    # Step 5: Onboarding pipeline (Upload, Validate, Confirm, Train, Poll)
    # -----------------------------------------------------------------------
    def step_5_onboarding_pipeline(self, jwt: str, tenant_id: str, csv_bytes: bytes) -> dict[str, Any]:
        t0 = time.perf_counter()
        headers = {"Authorization": f"Bearer {jwt}"}

        # 1. Upload
        upload_url = f"{self.base_url}/v1/onboard/upload"
        files = {"file": ("transactions.csv", csv_bytes, "text/csv")}
        u_resp = self.session.post(upload_url, files=files, headers=headers, timeout=30)
        if u_resp.status_code != 200:
            self.record_step(5, "Onboarding Pipeline", False, time.perf_counter() - t0, f"Upload failed ({u_resp.status_code}): {u_resp.text}")
            return {}

        profile_data = u_resp.json()

        # 2. Validate
        val_url = f"{self.base_url}/v1/onboard/validate"
        val_resp = self.session.post(val_url, json={}, headers=headers, timeout=30)
        if val_resp.status_code != 200:
            self.record_step(5, "Onboarding Pipeline", False, time.perf_counter() - t0, f"Validate failed ({val_resp.status_code}): {val_resp.text}")
            return {}

        candidate_cfg = val_resp.json().get("candidate_config")

        # 3. Confirm
        conf_url = f"{self.base_url}/v1/onboard/confirm"
        conf_payload = {
            "candidate_config": candidate_cfg,
            "auto_accept": True,
        }
        conf_resp = self.session.post(conf_url, json=conf_payload, headers=headers, timeout=30)
        if conf_resp.status_code != 200:
            self.record_step(5, "Onboarding Pipeline", False, time.perf_counter() - t0, f"Confirm failed ({conf_resp.status_code}): {conf_resp.text}")
            return {}

        # 4. Train
        train_url = f"{self.base_url}/v1/onboard/train"
        train_resp = self.session.post(train_url, json={}, headers=headers, timeout=30)
        if train_resp.status_code not in (200, 202):
            self.record_step(5, "Onboarding Pipeline", False, time.perf_counter() - t0, f"Train failed ({train_resp.status_code}): {train_resp.text}")
            return {}

        # 5. Poll status until completion
        status_url = f"{self.base_url}/v1/onboard/status"
        timeout_sec = 600.0
        poll_start = time.time()
        final_status = None

        print("      Polling tournament training status...", end="", flush=True)
        while time.time() - poll_start < timeout_sec:
            time.sleep(3.0)
            print(".", end="", flush=True)
            s_resp = self.session.get(status_url, headers=headers, timeout=15)
            if s_resp.status_code != 200:
                continue
            s_data = s_resp.json()
            st = s_data.get("status")
            if st in ("completed", "complete"):
                final_status = s_data
                print(" done!")
                break
            elif st in ("failed", "stalled"):
                print(" failed!")
                err_msg = s_data.get("error") or s_data.get("message")
                self.record_step(
                    5,
                    "Onboarding Pipeline",
                    False,
                    time.perf_counter() - t0,
                    f"Tournament training ended with status '{st}': {err_msg}",
                )
                return {}

        if not final_status:
            print(" timed out!")
            self.record_step(5, "Onboarding Pipeline", False, time.perf_counter() - t0, "Training polling timed out after 10 minutes")
            return {}

        self.record_step(
            5,
            "Onboarding Pipeline",
            True,
            time.perf_counter() - t0,
            f"Winner: {final_status.get('winner_model')} ({final_status.get('winner_key')})",
        )
        return final_status

    # -----------------------------------------------------------------------
    # Step 6: Disk assertions and model tournament evaluation
    # -----------------------------------------------------------------------
    def step_6_disk_assertions(self, tenant_id: str):
        t0 = time.perf_counter()

        expected_files = [
            f"data/raw/{tenant_id}_raw.csv",
            f"data/processed/{tenant_id}/customers.csv",
            f"data/processed/{tenant_id}/products.csv",
            f"data/processed/{tenant_id}/interactions.csv",
            f"models/{tenant_id}/final_model.joblib",
            f"status/{tenant_id}.json",
        ]

        missing = []
        for rel in expected_files:
            full_path = ROOT / rel
            if not full_path.exists():
                missing.append(rel)

        if missing:
            self.record_step(6, "Disk & Model Assertions", False, time.perf_counter() - t0, f"Missing files on disk: {missing}")
            return

        # Inspect status JSON
        status_file = ROOT / f"status/{tenant_id}.json"
        try:
            status_data = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception as exc:
            self.record_step(6, "Disk & Model Assertions", False, time.perf_counter() - t0, f"Cannot parse status file: {exc}")
            return

        models = status_data.get("models", {})
        if len(models) != 4:
            self.record_step(6, "Disk & Model Assertions", False, time.perf_counter() - t0, f"Expected 4 models in status, got {len(models)}: {models}")
            return

        done_models = [k for k, v in models.items() if v == "done"]
        if len(done_models) < 2:
            self.record_step(6, "Disk & Model Assertions", False, time.perf_counter() - t0, f"Expected at least 2 models 'done', got: {models}")
            return

        metrics = status_data.get("metrics", {})
        for dm in done_models:
            m_metrics = metrics.get(dm)
            if not m_metrics or m_metrics.get("ndcg") is None:
                self.record_step(6, "Disk & Model Assertions", False, time.perf_counter() - t0, f"Missing metrics for done model '{dm}'")
                return

        winner = status_data.get("winner_model")
        if not winner:
            self.record_step(6, "Disk & Model Assertions", False, time.perf_counter() - t0, "winner_model is not set")
            return

        failed_models = [f"{k} ({v})" for k, v in models.items() if v not in ("done", "completed")]
        failed_note = f" (Failed models: {', '.join(failed_models)})" if failed_models else " (All 4 models done)"

        detail = f"All artifacts verified on disk; {len(done_models)}/4 models completed successfully. Winner: {winner}{failed_note}"
        self.record_step(6, "Disk & Model Assertions", True, time.perf_counter() - t0, detail)

    # -----------------------------------------------------------------------
    # Step 7: Recommendations checks
    # -----------------------------------------------------------------------
    def step_7_recommendations(self, pk: str) -> list[str]:
        t0 = time.perf_counter()
        pk_headers = {"X-API-Key": pk}

        # 1. Sample customers
        sc_url = f"{self.base_url}/v1/recommendations/sample-customers?limit=10"
        sc_resp = self.session.get(sc_url, headers=pk_headers, timeout=10)
        if sc_resp.status_code != 200:
            self.record_step(7, "Recommendations Verification", False, time.perf_counter() - t0, f"Sample customers failed: {sc_resp.text}")
            return []

        customer_ids = sc_resp.json().get("customer_ids", [])
        if not customer_ids:
            self.record_step(7, "Recommendations Verification", False, time.perf_counter() - t0, "Sample customers returned empty list")
            return []

        first_customer = customer_ids[0]

        # 2. Recommendation with wizard-test header -> fallback=False
        rec_url = f"{self.base_url}/v1/recommendations/{first_customer}?top_n=5"
        test_headers = {"X-API-Key": pk, "X-AIPOD-Source": "wizard-test"}
        r_resp = self.session.get(rec_url, headers=test_headers, timeout=10)
        if r_resp.status_code != 200:
            self.record_step(7, "Recommendations Verification", False, time.perf_counter() - t0, f"Recommendation failed: {r_resp.text}")
            return []

        r_data = r_resp.json()
        if r_data.get("fallback") is not False:
            self.record_step(7, "Recommendations Verification", False, time.perf_counter() - t0, f"Expected fallback=False for known customer, got: {r_data}")
            return []

        if not r_data.get("recommendations"):
            self.record_step(7, "Recommendations Verification", False, time.perf_counter() - t0, f"Empty recommendations for known customer: {r_data}")
            return []

        # 3. Unknown customer -> 200 with fallback=True, reason=unknown_customer
        unk_url = f"{self.base_url}/v1/recommendations/UNKNOWN_CUSTOMER_9999?top_n=5"
        unk_resp = self.session.get(unk_url, headers=test_headers, timeout=10)
        if unk_resp.status_code != 200:
            self.record_step(7, "Recommendations Verification", False, time.perf_counter() - t0, f"Unknown customer failed with status {unk_resp.status_code}: {unk_resp.text}")
            return []

        unk_data = unk_resp.json()
        if unk_data.get("fallback") is not True or unk_data.get("reason") != "unknown_customer":
            self.record_step(7, "Recommendations Verification", False, time.perf_counter() - t0, f"Expected fallback=True and reason=unknown_customer, got: {unk_data}")
            return []

        self.record_step(
            7,
            "Recommendations Verification",
            True,
            time.perf_counter() - t0,
            f"Known customer ({first_customer}) returned {len(r_data['recommendations'])} recs (fallback=False); unknown customer returned 200 fallback=True reason=unknown_customer",
        )
        return customer_ids

    # -----------------------------------------------------------------------
    # Step 8: Telemetry and Dashboard assertions
    # -----------------------------------------------------------------------
    def step_8_telemetry_and_dashboard(self, pk: str, jwt: str, customer_ids: list[str]):
        t0 = time.perf_counter()
        pk_headers = {"X-API-Key": pk}
        jwt_headers = {"Authorization": f"Bearer {jwt}"}

        # 1. Send 6 tracking events
        events_to_send = [
            ("view", "PROD_001", "sess_001", customer_ids[0]),
            ("view", "PROD_002", "sess_001", customer_ids[0]),
            ("add_to_cart", "PROD_001", "sess_001", customer_ids[0]),
            ("add_to_cart", "PROD_002", "sess_002", customer_ids[1]),
            ("purchase", "PROD_001", "sess_001", customer_ids[0]),
            ("purchase", "PROD_002", "sess_002", customer_ids[1]),
        ]

        track_url = f"{self.base_url}/v1/track"
        for etype, pid, sid, cid in events_to_send:
            payload = {
                "event_type": etype,
                "product_id": pid,
                "session_id": sid,
                "customer_id": cid,
            }
            resp = self.session.post(track_url, json=payload, headers=pk_headers, timeout=10)
            if resp.status_code != 202:
                self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Tracking failed ({resp.status_code}): {resp.text}")
                return

        # 2. Send 5 recommendation requests WITHOUT wizard-test header
        for i in range(5):
            cid = customer_ids[i % len(customer_ids)]
            r_url = f"{self.base_url}/v1/recommendations/{cid}?top_n=5"
            resp = self.session.get(r_url, headers=pk_headers, timeout=10)
            if resp.status_code != 200:
                self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Live recommendation call {i} failed: {resp.text}")
                return

        # 3. Wait 8 seconds for background flusher
        print("      Waiting 8s for telemetry flusher...", flush=True)
        time.sleep(8.0)

        # 4. Check /v1/dashboard/events
        ev_url = f"{self.base_url}/v1/dashboard/events?limit=20"
        ev_resp = self.session.get(ev_url, headers=jwt_headers, timeout=10)
        if ev_resp.status_code != 200:
            self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Dashboard events failed: {ev_resp.text}")
            return

        events_data = ev_resp.json().get("events", [])
        if len(events_data) < 6:
            self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Expected at least 6 events in dashboard, got {len(events_data)}")
            return

        # 5. Check /v1/dashboard/analytics?days=7
        an_url = f"{self.base_url}/v1/dashboard/analytics?days=7"
        an_resp = self.session.get(an_url, headers=jwt_headers, timeout=10)
        if an_resp.status_code != 200:
            self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Dashboard analytics failed: {an_resp.text}")
            return

        an_data = an_resp.json()
        total_events = an_data.get("total_events", 0)
        total_recs = an_data.get("total_recommendations", 0)

        if total_events != 6:
            self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Expected exactly 6 total_events, got {total_events}")
            return

        if total_recs != 5:
            self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Expected exactly 5 total_recommendations (test request excluded), got {total_recs}")
            return

        # 6. Check /v1/dashboard/overview
        ov_url = f"{self.base_url}/v1/dashboard/overview"
        ov_resp = self.session.get(ov_url, headers=jwt_headers, timeout=10)
        if ov_resp.status_code != 200:
            self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Dashboard overview failed: {ov_resp.text}")
            return

        ov_data = ov_resp.json()
        req_today = ov_data.get("requests_today", 0)
        if req_today != 5:
            self.record_step(8, "Telemetry & Dashboard", False, time.perf_counter() - t0, f"Expected requests_today=5, got {req_today}")
            return

        self.record_step(
            8,
            "Telemetry & Dashboard",
            True,
            time.perf_counter() - t0,
            f"Events=6, Recommendations=5 (wizard-test call properly excluded), Overview requests_today=5",
        )

    # -----------------------------------------------------------------------
    # Step 9: Security and Multi-Tenant Isolation
    # -----------------------------------------------------------------------
    def step_9_security_and_isolation(self, pk: str, tenant_1_id: str):
        t0 = time.perf_counter()
        pk_headers = {"X-API-Key": pk}

        # 1. Public pk- key forbidden on admin endpoints
        onboard_status_resp = self.session.get(f"{self.base_url}/v1/onboard/status", headers=pk_headers)
        if onboard_status_resp.status_code != 403:
            self.record_step(9, "Security & Isolation", False, time.perf_counter() - t0, f"Expected 403 for pk- on /onboard/status, got {onboard_status_resp.status_code}")
            return

        dash_ov_resp = self.session.get(f"{self.base_url}/v1/dashboard/overview", headers=pk_headers)
        if dash_ov_resp.status_code != 403:
            self.record_step(9, "Security & Isolation", False, time.perf_counter() - t0, f"Expected 403 for pk- on /dashboard/overview, got {dash_ov_resp.status_code}")
            return

        # 2. No key -> 401
        no_auth_resp = self.session.get(f"{self.base_url}/v1/dashboard/overview")
        if no_auth_resp.status_code != 401:
            self.record_step(9, "Security & Isolation", False, time.perf_counter() - t0, f"Expected 401 without auth, got {no_auth_resp.status_code}")
            return

        # 3. Sign up second fresh tenant
        rand_hex2 = secrets.token_hex(4)
        c2 = self.step_3_signup_isolated(f"E2E Test Tenant2 {rand_hex2}", f"e2e_t2_{rand_hex2}@example.com")
        jwt2 = self.step_4_verify_and_login(c2)

        jwt2_headers = {"Authorization": f"Bearer {jwt2}"}
        t2_ov = self.session.get(f"{self.base_url}/v1/dashboard/overview", headers=jwt2_headers).json()
        if t2_ov.get("requests_today") != 0 or t2_ov.get("tenant_id") == tenant_1_id:
            self.record_step(9, "Security & Isolation", False, time.perf_counter() - t0, f"Cross-tenant leak: Tenant 2 saw Tenant 1 data: {t2_ov}")
            return

        t2_ev = self.session.get(f"{self.base_url}/v1/dashboard/events", headers=jwt2_headers).json()
        if t2_ev.get("events") != []:
            self.record_step(9, "Security & Isolation", False, time.perf_counter() - t0, f"Cross-tenant leak: Tenant 2 saw Tenant 1 events: {t2_ev}")
            return

        self.record_step(
            9,
            "Security & Isolation",
            True,
            time.perf_counter() - t0,
            "Public pk- forbidden (403), unauthenticated rejected (401), second tenant isolated (0 leak)",
        )

    def step_3_signup_isolated(self, name: str, email: str) -> dict[str, Any]:
        resp = self.session.post(
            f"{self.base_url}/v1/accounts/signup",
            json={"company_name": name, "email": email, "password": "TestPassword123!Secure"},
            timeout=15,
        )
        data = resp.json()
        return {
            "company_name": name,
            "email": email,
            "password": "TestPassword123!Secure",
            "tenant_id": data.get("tenant_id"),
            "pk": data.get("public_key"),
            "sk": data.get("private_key"),
        }

    # -----------------------------------------------------------------------
    # Step 10: Key Regeneration
    # -----------------------------------------------------------------------
    def step_10_key_regeneration(self, jwt: str, old_pk: str, old_sk: str) -> dict[str, str]:
        t0 = time.perf_counter()
        jwt_headers = {"Authorization": f"Bearer {jwt}"}

        regen_url = f"{self.base_url}/v1/accounts/keys/regenerate"
        resp = self.session.post(regen_url, headers=jwt_headers, timeout=10)
        if resp.status_code != 200:
            self.record_step(10, "Key Regeneration", False, time.perf_counter() - t0, f"Regenerate failed ({resp.status_code}): {resp.text}")
            return {}

        data = resp.json()
        new_pk = data.get("public_key")
        new_sk = data.get("private_key")

        if not new_pk or not new_sk or new_pk == old_pk or new_sk == old_sk:
            self.record_step(10, "Key Regeneration", False, time.perf_counter() - t0, f"Invalid keys returned: {data}")
            return {}

        # Assert old keys return 401
        old_pk_resp = self.session.get(f"{self.base_url}/v1/recommendations?customer_id=CUST_0001", headers={"X-API-Key": old_pk})
        if old_pk_resp.status_code != 401:
            self.record_step(10, "Key Regeneration", False, time.perf_counter() - t0, f"Old pk returned {old_pk_resp.status_code} instead of 401")
            return {}

        old_sk_resp = self.session.get(f"{self.base_url}/v1/dashboard/overview", headers={"X-API-Key": old_sk})
        if old_sk_resp.status_code != 401:
            self.record_step(10, "Key Regeneration", False, time.perf_counter() - t0, f"Old sk returned {old_sk_resp.status_code} instead of 401")
            return {}

        # Assert new pk works immediately
        new_pk_resp = self.session.get(f"{self.base_url}/v1/recommendations/sample-customers", headers={"X-API-Key": new_pk})
        if new_pk_resp.status_code != 200:
            self.record_step(10, "Key Regeneration", False, time.perf_counter() - t0, f"New pk failed ({new_pk_resp.status_code}): {new_pk_resp.text}")
            return {}

        self.record_step(
            10,
            "Key Regeneration",
            True,
            time.perf_counter() - t0,
            "Old keys invalidated (401); new pk works immediately without server restart",
        )
        return {"pk": new_pk, "sk": new_sk}

    # -----------------------------------------------------------------------
    # Step 11: Summary and Credentials Output
    # -----------------------------------------------------------------------
    def step_11_print_summary(self, creds: dict[str, Any], new_keys: dict[str, str]):
        total_time = sum(r["duration"] for r in self.results)
        print("\n" + "=" * 70)
        print(f"{BOLD}{CYAN}AI_POD END-TO-END SMOKE TEST SUMMARY REPORT{RESET}")
        print("=" * 70)
        print(f"Server Target:        {self.base_url}")
        print(f"Tenant Identifier:    {creds.get('tenant_id')}")
        print(f"Company Account:      {creds.get('company_name')}")
        print(f"Login Email:          {creds.get('email')}")
        print(f"Login Password:       {creds.get('password')}")
        print(f"Initial Public Key:   {creds.get('pk')}")
        print(f"Active Public Key:    {new_keys.get('pk')}")
        print(f"Active Private Key:   {new_keys.get('sk')}")
        print("-" * 70)
        print(f"{'Step':<6} {'Name':<36} {'Status':<10} {'Duration':<10}")
        print("-" * 70)
        for r in self.results:
            st = f"{GREEN}PASS{RESET}" if r["success"] else f"{RED}FAIL{RESET}"
            print(f"{r['step']:<6} {r['name']:<36} {st:<19} {r['duration']:>6.2f}s")
        print("-" * 70)
        print(f"Total Execution Time: {total_time:.2f}s ({len(self.results)}/10 steps passed)")
        print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Cleanup Routine
# ---------------------------------------------------------------------------

def perform_cleanup(yes: bool = False):
    """Delete ONLY artifacts of tenants whose company name starts with 'E2E Test'."""
    print(f"\n{YELLOW}--- AI_POD E2E Test Tenant Cleanup ---{RESET}")
    config_path = ROOT / "config" / "config.yaml"
    accounts_path = ROOT / "config" / "accounts.local.yaml"
    auth_path = ROOT / "config" / "tenants_auth.local.yaml"

    if not config_path.exists():
        print("config/config.yaml not found.")
        return

    # 1. Identify E2E test tenants from accounts
    e2e_tenants = set()
    if accounts_path.exists():
        try:
            import yaml
            acc_data = yaml.safe_load(accounts_path.read_text(encoding="utf-8")) or {}
            for acc in acc_data.values():
                if isinstance(acc, dict):
                    cname = acc.get("company_name", "")
                    tid = acc.get("tenant_id")
                    if (cname.startswith("E2E Test") or (tid and tid.startswith("e2e_test_"))) and tid:
                        e2e_tenants.add(tid)
        except Exception as exc:
            print(f"Warning reading accounts: {exc}")

    # Also scan config.yaml for e2e_test_
    try:
        import yaml
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        for tid, tval in (cfg.get("tenants") or {}).items():
            if tid.startswith("e2e_test_") or (isinstance(tval, dict) and tval.get("display_name", "").startswith("E2E Test")):
                e2e_tenants.add(tid)
    except Exception as exc:
        print(f"Warning reading config: {exc}")

    if not e2e_tenants:
        print("No E2E test tenants found to clean up.")
        return

    print(f"Found {len(e2e_tenants)} E2E test tenant(s) to remove: {sorted(e2e_tenants)}")

    if not yes:
        ans = input("Are you sure you want to delete all E2E Test tenant artifacts? (y/N): ").strip().lower()
        if ans not in ("y", "yes"):
            print("Cleanup cancelled.")
            return

    # Delete artifacts on disk
    removed_items = 0
    for tid in e2e_tenants:
        paths_to_delete = [
            ROOT / f"data/raw/{tid}_raw.csv",
            ROOT / f"data/processed/{tid}",
            ROOT / f"models/{tid}",
            ROOT / f"status/{tid}.json",
            ROOT / f"status/{tid}_dataset_stats.json",
            ROOT / f"data/telemetry/{tid}",
        ]
        for p in paths_to_delete:
            if p.exists():
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                removed_items += 1

    # Remove from config.yaml
    try:
        from src.utils.atomic_yaml import atomic_dump_yaml
        import yaml
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if "tenants" in cfg:
            changed = False
            for tid in e2e_tenants:
                if tid in cfg["tenants"]:
                    del cfg["tenants"][tid]
                    changed = True
            if changed:
                atomic_dump_yaml(config_path, cfg)
                print("Updated config/config.yaml.")
    except Exception as exc:
        print(f"Error updating config.yaml: {exc}")

    # Remove from accounts and tenants_auth
    for fpath in (accounts_path, auth_path):
        if fpath.exists():
            try:
                import yaml
                from src.utils.atomic_yaml import atomic_dump_yaml
                data = yaml.safe_load(fpath.read_text(encoding="utf-8")) or {}
                filtered = {}
                for k, v in data.items():
                    if isinstance(v, dict):
                        if v.get("tenant_id") in e2e_tenants:
                            continue
                        if v.get("company_name", "").startswith("E2E Test"):
                            continue
                    filtered[k] = v
                atomic_dump_yaml(fpath, filtered)
            except Exception as exc:
                print(f"Error filtering {fpath.name}: {exc}")

    print(f"{GREEN}Cleanup complete. Removed artifacts across {len(e2e_tenants)} test tenant(s).{RESET}\n")


# ---------------------------------------------------------------------------
# After-Restart Verification Routine
# ---------------------------------------------------------------------------

def perform_after_restart(base_url: str, tenant_id: str, email: str, password: str):
    """Re-run login, recommendations, and key checks to prove persistence after restarting uvicorn."""
    print(f"\n{BOLD}{CYAN}--- AI_POD Post-Restart Persistence Verification ---{RESET}")
    print(f"Base URL:  {base_url}")
    print(f"Tenant ID: {tenant_id}")
    print(f"Email:     {email}\n")

    session = requests.Session()

    # 1. Login
    print("1. Logging in with credentials...", end="", flush=True)
    l_resp = session.post(f"{base_url}/v1/accounts/login", json={"email": email, "password": password}, timeout=10)
    if l_resp.status_code != 200:
        print(f" {RED}FAIL ({l_resp.status_code}): {l_resp.text}{RESET}")
        sys.exit(1)
    token = (
        l_resp.json().get("session_token")
        or l_resp.json().get("access_token")
        or l_resp.json().get("token")
    )
    print(f" {GREEN}OK{RESET} (JWT obtained)")

    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check /accounts/me
    print("2. Checking /v1/accounts/me...", end="", flush=True)
    me_resp = session.get(f"{base_url}/v1/accounts/me", headers=headers, timeout=10)
    if me_resp.status_code != 200:
        print(f" {RED}FAIL ({me_resp.status_code}){RESET}")
        sys.exit(1)
    me_data = me_resp.json()
    pk = me_data.get("public_key")
    if me_data.get("tenant_id") != tenant_id or not pk:
        print(f" {RED}FAIL (mismatch: {me_data}){RESET}")
        sys.exit(1)
    print(f" {GREEN}OK{RESET} (Tenant: {tenant_id}, PK: {pk})")

    # 3. Check /dashboard/overview
    print("3. Checking /v1/dashboard/overview...", end="", flush=True)
    ov_resp = session.get(f"{base_url}/v1/dashboard/overview", headers=headers, timeout=10)
    if ov_resp.status_code != 200:
        print(f" {RED}FAIL ({ov_resp.status_code}){RESET}")
        sys.exit(1)
    ov_data = ov_resp.json()
    if not ov_data.get("ready") or ov_data.get("status") != "completed":
        print(f" {RED}FAIL (model not ready: {ov_data}){RESET}")
        sys.exit(1)
    print(f" {GREEN}OK{RESET} (Winner: {ov_data.get('winning_model')}, NDCG@5: {ov_data.get('metrics', {}).get('ndcg')})")

    # 4. Check live recommendations
    print("4. Testing live recommendations with PK...", end="", flush=True)
    sc_resp = session.get(f"{base_url}/v1/recommendations/sample-customers?limit=3", headers={"X-API-Key": pk}, timeout=10)
    if sc_resp.status_code != 200:
        print(f" {RED}FAIL ({sc_resp.status_code}){RESET}")
        sys.exit(1)
    cids = sc_resp.json().get("customer_ids", [])
    if not cids:
        print(f" {RED}FAIL (no sample customers){RESET}")
        sys.exit(1)

    rec_resp = session.get(f"{base_url}/v1/recommendations/{cids[0]}?top_n=5", headers={"X-API-Key": pk}, timeout=10)
    if rec_resp.status_code != 200:
        print(f" {RED}FAIL ({rec_resp.status_code}){RESET}")
        sys.exit(1)
    rdata = rec_resp.json()
    if rdata.get("fallback") is not False or not rdata.get("recommendations"):
        print(f" {RED}FAIL (fallback served: {rdata}){RESET}")
        sys.exit(1)
    print(f" {GREEN}OK{RESET} (Served {len(rdata['recommendations'])} items from model)")

    print(f"\n{GREEN}{BOLD}[PASS] Post-restart persistence test PASSED successfully!{RESET}\n")


# ---------------------------------------------------------------------------
# Main CLI Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AI_POD End-to-End Smoke Test Suite")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base URL of running server")
    parser.add_argument("--cleanup", action="store_true", help="Delete all artifacts of 'E2E Test' tenants")
    parser.add_argument("--yes", "-y", action="store_true", help="Confirm cleanup without prompt")
    parser.add_argument(
        "--after-restart",
        nargs=3,
        metavar=("TENANT", "EMAIL", "PASSWORD"),
        help="Verify persistence after restarting the server",
    )

    args = parser.parse_args()

    if args.cleanup:
        perform_cleanup(yes=args.yes)
        return

    if args.after_restart:
        perform_after_restart(args.base_url, args.after_restart[0], args.after_restart[1], args.after_restart[2])
        return

    print(f"\n{BOLD}{CYAN}Starting AI_POD End-to-End Smoke Test on {args.base_url}...{RESET}\n")
    runner = SmokeTestRunner(base_url=args.base_url)

    # 1. Health check
    runner.step_1_health_check()

    # 2. Synthetic dataset
    csv_bytes = runner.step_2_generate_dataset()

    # 3. Signup
    creds = runner.step_3_signup()

    # 4. Verify & Login
    jwt = runner.step_4_verify_and_login(creds)

    # 5. Onboarding Pipeline
    runner.step_5_onboarding_pipeline(jwt, creds["tenant_id"], csv_bytes)

    # 6. Disk Assertions
    runner.step_6_disk_assertions(creds["tenant_id"])

    # 7. Recommendations
    sample_customers = runner.step_7_recommendations(creds["pk"])

    # 8. Telemetry & Dashboard
    runner.step_8_telemetry_and_dashboard(creds["pk"], jwt, sample_customers)

    # 9. Security & Isolation
    runner.step_9_security_and_isolation(creds["pk"], creds["tenant_id"])

    # 10. Key Regeneration
    new_keys = runner.step_10_key_regeneration(jwt, creds["pk"], creds["sk"])

    # 11. Summary
    runner.step_11_print_summary(creds, new_keys)


if __name__ == "__main__":
    main()
