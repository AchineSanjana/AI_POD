"""Tests for unified admin authentication, atomic writes, and key lifecycle.

Covers:
- get_tenant_for_admin_action accepts private sk- keys and valid session JWTs.
- Rejection of pk- public keys on /v1/onboard/* with 403 Forbidden.
- Rejection of MFA tickets on /v1/onboard/* with 401 Unauthorized.
- JWT accepted on onboarding for owner tenant only (cross-tenant rejected with 403).
- Enforcement of email verification on JWT onboarding (403 when enabled and unverified).
- Regenerate keys immediately 401s old keys, and new keys work without restart.
- Atomic write survives a simulated crash (exception leaves old file intact).
- Concurrent thread writes do not corrupt storage files.
- GET /v1/accounts/me returns tenant_id, public_key, email_verified, mfa_enabled,
  is_admin, key_created_at, has_private_key (and never private_key).
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
import yaml

from src.accounts.service import (
    issue_tenant_keys,
    login_company_account,
    signup_company_account,
    verify_account_email,
)
from src.accounts.session import create_mfa_ticket
from src.api.app import app
from src.utils.atomic_yaml import atomic_dump_yaml


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def clean_test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate accounts and tenants_auth into a temporary test directory."""
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("ENFORCE_EMAIL_VERIFICATION", "false")

    from src.api.rate_limiter import RATE_LIMITER, SIGNUP_RATE_LIMITER
    RATE_LIMITER.reset()
    SIGNUP_RATE_LIMITER.reset()

    temp_accounts = tmp_path / "accounts.local.yaml"
    temp_auth = tmp_path / "tenants_auth.local.yaml"
    temp_config = tmp_path / "config.yaml"

    initial_config = {
        "tenants": {
            "telco_default": {"display_name": "Telco Default"},
        },
        "storage": {"backend": "local"},
    }
    with open(temp_config, "w", encoding="utf-8") as f:
        yaml.safe_dump(initial_config, f)

    def mock_resolve_path(rel_path):
        rel_str = str(rel_path).replace("\\", "/")
        if rel_str == "config/accounts.local.yaml":
            return temp_accounts
        if rel_str == "config/tenants_auth.local.yaml":
            return temp_auth
        if rel_str == "config/config.yaml":
            return temp_config
        return Path(tmp_path) / rel_str

    monkeypatch.setattr("src.accounts.storage.resolve_path", mock_resolve_path)
    monkeypatch.setattr("src.accounts.storage.LOCAL_ACCOUNTS_FILE", str(temp_accounts))
    monkeypatch.setattr("src.utils.key_manager.resolve_path", mock_resolve_path)
    monkeypatch.setattr("src.api.onboarding.resolve_path", mock_resolve_path)
    monkeypatch.setattr("src.utils.config.resolve_path", mock_resolve_path)
    monkeypatch.setattr("src.utils.config.DEFAULT_CONFIG_PATH", temp_config)

    from src.api.auth import TENANT_AUTH_MAPPING, TENANT_KEY_RECORDS, load_tenant_auth
    TENANT_AUTH_MAPPING.clear()
    TENANT_KEY_RECORDS.clear()
    load_tenant_auth(initial_config)

    return {
        "accounts_file": temp_accounts,
        "auth_file": temp_auth,
        "config_file": temp_config,
    }


def test_onboarding_accepts_private_sk_key(client: TestClient, clean_test_env):
    """Private sk- key is authorized for /v1/onboard/status."""
    signup_res = signup_company_account(
        company_name="Sk Test Corp",
        email="sktest@example.com",
        password="ValidPassword123!",
    )
    sk = signup_res["private_key"]
    tenant_id = signup_res["tenant_id"]

    resp = client.get("/v1/onboard/status", headers={"X-API-Key": sk})
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == tenant_id


def test_onboarding_rejects_public_pk_key_with_403(client: TestClient, clean_test_env):
    """Public pk- key must be rejected on /v1/onboard/* endpoints with 403 Forbidden."""
    signup_res = signup_company_account(
        company_name="Pk Test Corp",
        email="pktest@example.com",
        password="ValidPassword123!",
    )
    pk = signup_res["public_key"]

    resp = client.get("/v1/onboard/status", headers={"X-API-Key": pk})
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "public" in detail.lower() and ("forbidden" in detail.lower() or "cannot perform" in detail.lower())


def test_onboarding_rejects_mfa_ticket_with_401(client: TestClient, clean_test_env):
    """MFA challenge ticket must be rejected with 401 Unauthorized."""
    signup_res = signup_company_account(
        company_name="Mfa Test Corp",
        email="mfatest@example.com",
        password="ValidPassword123!",
    )
    mfa_ticket = create_mfa_ticket(
        account_id=signup_res["account_id"],
        tenant_id=signup_res["tenant_id"],
        email=signup_res["email"],
    )

    resp = client.get(
        "/v1/onboard/status",
        headers={"Authorization": f"Bearer {mfa_ticket}"},
    )
    assert resp.status_code == 401
    assert "MFA challenge ticket cannot be used as a session token" in resp.json()["detail"]


def test_onboarding_accepts_jwt_for_owner_tenant_only(client: TestClient, clean_test_env):
    """JWT session token is accepted for the owner tenant, but rejects cross-tenant actions."""
    signup_a = signup_company_account(
        company_name="Tenant Alpha",
        email="alpha@example.com",
        password="ValidPassword123!",
    )
    signup_b = signup_company_account(
        company_name="Tenant Beta",
        email="beta@example.com",
        password="ValidPassword123!",
    )

    login_a = login_company_account("alpha@example.com", "ValidPassword123!")
    token_a = login_a["access_token"]

    # Status returns tenant Alpha
    resp_status = client.get(
        "/v1/onboard/status",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_status.status_code == 200
    assert resp_status.json()["tenant_id"] == signup_a["tenant_id"]

    # Cross-tenant confirm attempt with candidate_config specifying tenant Beta is rejected
    cross_confirm = client.post(
        "/v1/onboard/confirm",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "candidate_config": {"tenant_id": signup_b["tenant_id"]},
        },
    )
    assert cross_confirm.status_code == 403
    assert "You can only configure your own tenant" in cross_confirm.json()["detail"]

    # Register-key for tenant Beta with token Alpha is rejected
    cross_reg = client.post(
        "/v1/onboard/register-key",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "tenant_id": signup_b["tenant_id"],
            "api_key": "sk-beta-customkey1234567890",
            "key_type": "private",
        },
    )
    assert cross_reg.status_code == 403
    assert "You can only register keys for your own tenant" in cross_reg.json()["detail"]


def test_onboarding_enforces_email_verification_when_enabled(
    client: TestClient, clean_test_env, monkeypatch: pytest.MonkeyPatch
):
    """When ENFORCE_EMAIL_VERIFICATION=true, unverified accounts get 403 on onboarding."""
    monkeypatch.setenv("ENFORCE_EMAIL_VERIFICATION", "true")

    signup_res = signup_company_account(
        company_name="Verify Corp",
        email="verify@example.com",
        password="ValidPassword123!",
    )
    account_id = signup_res["account_id"]

    # Login without email verification fails with 403
    from src.accounts.session import create_session_token
    token = create_session_token(account_id, signup_res["tenant_id"], "verify@example.com")

    # Onboarding with this unverified JWT gets 403
    resp_unverified = client.get(
        "/v1/onboard/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_unverified.status_code == 403
    assert "Email has not been verified" in resp_unverified.json()["detail"]

    # Verify the email
    from src.accounts.verification import RECENT_VERIFICATION_EMAILS
    code = RECENT_VERIFICATION_EMAILS["verify@example.com"]["code"]
    verify_account_email("verify@example.com", code)

    # Now onboarding succeeds
    resp_verified = client.get(
        "/v1/onboard/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_verified.status_code == 200
    assert resp_verified.json()["tenant_id"] == signup_res["tenant_id"]


def test_regenerate_keys_invalidates_old_immediately_and_new_work(
    client: TestClient, clean_test_env
):
    """Old keys immediately return 401, while regenerated keys work without restart."""
    signup_res = signup_company_account(
        company_name="Regen Corp",
        email="regen@example.com",
        password="ValidPassword123!",
    )
    old_sk = signup_res["private_key"]
    old_pk = signup_res["public_key"]

    login_res = login_company_account("regen@example.com", "ValidPassword123!")
    token = login_res["access_token"]

    # Verify old sk works
    assert client.get("/v1/onboard/status", headers={"X-API-Key": old_sk}).status_code == 200

    # Regenerate keys
    regen_resp = client.post(
        "/v1/accounts/keys/regenerate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert regen_resp.status_code == 200
    new_sk = regen_resp.json()["private_key"]
    new_pk = regen_resp.json()["public_key"]
    assert new_sk != old_sk
    assert new_pk != old_pk

    # Old keys immediately return 401
    old_sk_resp = client.get("/v1/onboard/status", headers={"X-API-Key": old_sk})
    assert old_sk_resp.status_code == 401

    old_pk_resp = client.get("/v1/recommendations/cust123", headers={"X-API-Key": old_pk})
    assert old_pk_resp.status_code == 401

    # New keys work immediately without restart
    new_sk_resp = client.get("/v1/onboard/status", headers={"X-API-Key": new_sk})
    assert new_sk_resp.status_code == 200

    new_pk_resp = client.get("/v1/recommendations/cust123", headers={"X-API-Key": new_pk})
    assert new_pk_resp.status_code == 200


def test_atomic_write_survives_simulated_crash(tmp_path: Path):
    """An exception during write/flush/fsync leaves the existing file completely intact."""
    target_file = tmp_path / "test_target.yaml"
    initial_data = {"version": 1, "status": "original_intact"}

    # Write initial data
    atomic_dump_yaml(target_file, initial_data)
    assert target_file.exists()

    # Simulate crash/exception during safe_dump
    def crashing_dump(*args, **kwargs):
        raise OSError("Simulated disk error or crash during write")

    with patch("yaml.safe_dump", side_effect=crashing_dump):
        with pytest.raises(OSError, match="Simulated disk error"):
            atomic_dump_yaml(target_file, {"version": 2, "status": "corrupted"})

    # Ensure original file remains untouched
    with open(target_file, encoding="utf-8") as f:
        survived = yaml.safe_load(f)
    assert survived == initial_data

    # Ensure no leftover temporary files in directory
    temp_files = list(tmp_path.glob("*.tmp"))
    assert len(temp_files) == 0


def test_concurrent_signups_do_not_corrupt_files(client: TestClient, clean_test_env):
    """Concurrent signup threads must not corrupt accounts.local.yaml or tenants_auth.local.yaml."""
    num_threads = 8

    def do_signup(idx: int):
        return signup_company_account(
            company_name=f"Concurrent Corp {idx}",
            email=f"concurrent{idx}@example.com",
            password="Password123!",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(do_signup, i) for i in range(num_threads)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == num_threads

    # Verify accounts file contains all signups
    accounts_file = clean_test_env["accounts_file"]
    with open(accounts_file, encoding="utf-8") as f:
        accounts_data = yaml.safe_load(f)

    assert "accounts" in accounts_data
    assert len(accounts_data["accounts"]) == num_threads

    # Verify tenants_auth contains keys for all signups (2 keys per tenant: sk + pk)
    auth_file = clean_test_env["auth_file"]
    with open(auth_file, encoding="utf-8") as f:
        auth_data = yaml.safe_load(f)

    assert "tenants_auth" in auth_data
    assert len(auth_data["tenants_auth"]) == num_threads * 2


def test_get_accounts_me_returns_all_required_fields(client: TestClient, clean_test_env):
    """GET /v1/accounts/me returns tenant_id, public_key, email_verified, mfa_enabled,

    is_admin, key_created_at and has_private_key (and never private_key).
    """
    signup_res = signup_company_account(
        company_name="Me Profile Test",
        email="meprofile@example.com",
        password="ValidPassword123!",
    )
    pk = signup_res["public_key"]
    sk = signup_res["private_key"]
    tenant_id = signup_res["tenant_id"]

    login_res = login_company_account("meprofile@example.com", "ValidPassword123!")
    token = login_res["access_token"]

    resp = client.get("/v1/accounts/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["tenant_id"] == tenant_id
    assert data["public_key"] == pk
    assert data["email_verified"] is False
    assert data["mfa_enabled"] is False
    assert data["is_admin"] is False
    assert data["has_private_key"] is True
    assert data["key_created_at"] is not None

    # CRITICAL SECURITY: Never expose private key
    assert "private_key" not in data
    assert sk not in resp.text
