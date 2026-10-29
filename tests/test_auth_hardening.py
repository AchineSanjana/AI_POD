"""Tests for hardened authentication: Email verification, TOTP MFA, brute-force lockout, and production key safety."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.accounts.totp import (
    generate_totp_code,
)
from src.api.app import app
from src.api.rate_limiter import SIGNUP_RATE_LIMITER


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    SIGNUP_RATE_LIMITER.reset()
    yield
    SIGNUP_RATE_LIMITER.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def clean_accounts(tmp_path, monkeypatch):
    temp_accounts = tmp_path / "accounts.local.yaml"
    temp_auth = tmp_path / "tenants_auth.local.yaml"

    monkeypatch.setattr("src.accounts.storage.LOCAL_ACCOUNTS_FILE", str(temp_accounts))
    monkeypatch.setenv("STORAGE_BACKEND", "local")

    import src.utils.config as cfg_module

    orig_resolve = cfg_module.resolve_path

    def mock_resolve_path(rel):
        rel_str = str(rel).replace("\\", "/")
        if rel_str == "config/tenants_auth.local.yaml":
            return temp_auth
        return orig_resolve(rel)

    monkeypatch.setattr("src.utils.config.resolve_path", mock_resolve_path)
    monkeypatch.setattr("src.utils.key_manager.resolve_path", mock_resolve_path)

    yield temp_accounts


def test_signup_dispatches_verification_code(client: TestClient, clean_accounts):
    """Signup dispatches a 6-digit verification code and leaves email_verified as False."""
    payload = {
        "company_name": "Secure Corp",
        "email": "dev@securecorp.com",
        "password": "SecurePassword123!",
    }
    resp = client.post("/v1/accounts/signup", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email_verified"] is False
    assert data["verification_sent"] is True
    assert "verification_code" in data
    code = data["verification_code"]
    assert len(code) == 6
    assert code.isdigit()


def test_verify_email_success_and_failure(client: TestClient, clean_accounts):
    """Email verification accepts the correct code and rejects invalid codes."""
    signup_payload = {
        "company_name": "Verify Corp",
        "email": "verify@testcorp.com",
        "password": "Password123!",
    }
    signup_resp = client.post("/v1/accounts/signup", json=signup_payload)
    assert signup_resp.status_code == 201
    code = signup_resp.json()["verification_code"]

    # 1. Invalid code rejected
    bad_resp = client.post(
        "/v1/accounts/verify-email",
        json={"email": "verify@testcorp.com", "code": "000000"},
    )
    assert bad_resp.status_code == 400
    assert "Invalid verification code" in bad_resp.json()["detail"]

    # 2. Valid code succeeds
    good_resp = client.post(
        "/v1/accounts/verify-email",
        json={"email": "verify@testcorp.com", "code": code},
    )
    assert good_resp.status_code == 200
    assert good_resp.json()["email_verified"] is True

    # 3. Repeat verification idempotently succeeds
    repeat_resp = client.post(
        "/v1/accounts/verify-email",
        json={"email": "verify@testcorp.com", "code": code},
    )
    assert repeat_resp.status_code == 200
    assert repeat_resp.json()["already_verified"] is True


def test_resend_verification_email(client: TestClient, clean_accounts):
    """Resend verification code dispatches a fresh code."""
    signup_payload = {
        "company_name": "Resend Corp",
        "email": "resend@testcorp.com",
        "password": "Password123!",
    }
    client.post("/v1/accounts/signup", json=signup_payload)

    resend_resp = client.post(
        "/v1/accounts/resend-verification",
        json={"email": "resend@testcorp.com"},
    )
    assert resend_resp.status_code == 200
    data = resend_resp.json()
    assert data["verification_sent"] is True
    assert len(data["verification_code"]) == 6


def test_login_brute_force_lockout(client: TestClient, clean_accounts):
    """5 consecutive failed login attempts locks the account."""
    signup_payload = {
        "company_name": "Lockout Corp",
        "email": "lockout@testcorp.com",
        "password": "CorrectPassword123!",
    }
    client.post("/v1/accounts/signup", json=signup_payload)

    # 4 bad attempts
    for _ in range(4):
        resp = client.post(
            "/v1/accounts/login",
            json={"email": "lockout@testcorp.com", "password": "WrongPassword!"},
        )
        assert resp.status_code == 401

    # 5th bad attempt triggers 423 Locked
    locked_resp = client.post(
        "/v1/accounts/login",
        json={"email": "lockout@testcorp.com", "password": "WrongPassword!"},
    )
    assert locked_resp.status_code == 423
    assert "temporarily locked" in locked_resp.json()["detail"].lower()

    # Even with correct password, login is blocked while locked
    correct_blocked = client.post(
        "/v1/accounts/login",
        json={"email": "lockout@testcorp.com", "password": "CorrectPassword123!"},
    )
    assert correct_blocked.status_code == 423


def test_enforce_email_verification_blocks_unverified_login(
    client: TestClient, clean_accounts, monkeypatch
):
    """When ENFORCE_EMAIL_VERIFICATION is True, unverified logins are rejected with 403."""
    monkeypatch.setenv("ENFORCE_EMAIL_VERIFICATION", "true")

    signup_payload = {
        "company_name": "Strict Corp",
        "email": "strict@testcorp.com",
        "password": "StrictPassword123!",
    }
    signup_resp = client.post("/v1/accounts/signup", json=signup_payload)
    code = signup_resp.json()["verification_code"]

    # Login before verification fails with 403 Forbidden
    login_resp = client.post(
        "/v1/accounts/login",
        json={"email": "strict@testcorp.com", "password": "StrictPassword123!"},
    )
    assert login_resp.status_code == 403
    assert "not been verified" in login_resp.json()["detail"].lower()

    # Verify email
    verif_resp = client.post(
        "/v1/accounts/verify-email",
        json={"email": "strict@testcorp.com", "code": code},
    )
    assert verif_resp.status_code == 200

    # Now login succeeds
    good_login = client.post(
        "/v1/accounts/login",
        json={"email": "strict@testcorp.com", "password": "StrictPassword123!"},
    )
    assert good_login.status_code == 200
    assert "access_token" in good_login.json()


def test_totp_mfa_full_lifecycle(client: TestClient, clean_accounts):
    """Test complete MFA setup, activation, 2FA challenge login, and disable flow."""
    # 1. Register and log in
    signup_payload = {
        "company_name": "MFA Corp",
        "email": "mfa@testcorp.com",
        "password": "SecretPassword123!",
    }
    client.post("/v1/accounts/signup", json=signup_payload)
    login_resp = client.post(
        "/v1/accounts/login",
        json={"email": "mfa@testcorp.com", "password": "SecretPassword123!"},
    )
    session_token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {session_token}"}

    # 2. Setup MFA -> get secret and otpauth URL
    setup_resp = client.post("/v1/accounts/mfa/setup", headers=headers)
    assert setup_resp.status_code == 200
    setup_data = setup_resp.json()
    secret = setup_data["secret"]
    assert setup_data["otpauth_url"].startswith("otpauth://totp/")

    # 3. Try enabling with wrong code -> fails
    bad_enable = client.post(
        "/v1/accounts/mfa/enable",
        headers=headers,
        json={"code": "000000"},
    )
    assert bad_enable.status_code == 401

    # 4. Enable with valid TOTP code
    totp_code = generate_totp_code(secret)
    enable_resp = client.post(
        "/v1/accounts/mfa/enable",
        headers=headers,
        json={"code": totp_code},
    )
    assert enable_resp.status_code == 200
    enable_data = enable_resp.json()
    assert enable_data["mfa_enabled"] is True
    backup_codes = enable_data["backup_codes"]
    assert len(backup_codes) == 8

    # Check /me shows mfa_enabled=True
    me_resp = client.get("/v1/accounts/me", headers=headers)
    assert me_resp.json()["mfa_enabled"] is True

    # 5. Subsequent login now returns MFA challenge ticket
    mfa_login_init = client.post(
        "/v1/accounts/login",
        json={"email": "mfa@testcorp.com", "password": "SecretPassword123!"},
    )
    assert mfa_login_init.status_code == 200
    init_data = mfa_login_init.json()
    assert init_data["mfa_required"] is True
    assert "mfa_ticket" in init_data
    mfa_ticket = init_data["mfa_ticket"]

    # Verify that challenge ticket cannot access protected /me endpoint
    ticket_me = client.get(
        "/v1/accounts/me", headers={"Authorization": f"Bearer {mfa_ticket}"}
    )
    assert ticket_me.status_code == 401

    # 6. Complete MFA step with TOTP code
    second_code = generate_totp_code(secret)
    mfa_complete = client.post(
        "/v1/accounts/login/mfa",
        json={"mfa_ticket": mfa_ticket, "code": second_code},
    )
    assert mfa_complete.status_code == 200
    final_data = mfa_complete.json()
    assert "access_token" in final_data

    # 7. Complete MFA step with a Backup Recovery Code
    mfa_login_backup = client.post(
        "/v1/accounts/login",
        json={"email": "mfa@testcorp.com", "password": "SecretPassword123!"},
    )
    backup_ticket = mfa_login_backup.json()["mfa_ticket"]
    used_backup_code = backup_codes[0]

    backup_login_resp = client.post(
        "/v1/accounts/login/mfa",
        json={"mfa_ticket": backup_ticket, "code": used_backup_code},
    )
    assert backup_login_resp.status_code == 200
    assert "access_token" in backup_login_resp.json()

    # Re-using the same backup code must fail
    mfa_login_reuse = client.post(
        "/v1/accounts/login",
        json={"email": "mfa@testcorp.com", "password": "SecretPassword123!"},
    )
    reuse_ticket = mfa_login_reuse.json()["mfa_ticket"]
    reuse_resp = client.post(
        "/v1/accounts/login/mfa",
        json={"mfa_ticket": reuse_ticket, "code": used_backup_code},
    )
    assert reuse_resp.status_code == 401

    # 8. Disable MFA
    current_totp = generate_totp_code(secret)
    disable_resp = client.post(
        "/v1/accounts/mfa/disable",
        headers={"Authorization": f"Bearer {backup_login_resp.json()['access_token']}"},
        json={"password": "SecretPassword123!", "code": current_totp},
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["mfa_enabled"] is False

    # After disabling, normal login succeeds directly without MFA challenge
    direct_login = client.post(
        "/v1/accounts/login",
        json={"email": "mfa@testcorp.com", "password": "SecretPassword123!"},
    )
    assert direct_login.status_code == 200
    assert direct_login.json()["mfa_required"] is False
    assert "access_token" in direct_login.json()


def test_production_blocks_wildcard_xxxx_mock_keys(client: TestClient, monkeypatch):
    """When in production, wildcard -xxxx test keys are strictly rejected."""
    from src.api.auth import TENANT_KEY_RECORDS, get_key_record

    # Under test/dev (default), mock key works:
    dev_record = get_key_record("sk-telco-xxxx")
    assert dev_record is not None
    assert dev_record["tenant_id"] == "telco_default"

    # When marked as production, mock key must return None and 401 Unauthorized
    monkeypatch.setenv("ENV", "production")
    TENANT_KEY_RECORDS.clear()  # Flush cached resolution

    prod_record = get_key_record("sk-telco-xxxx")
    assert prod_record is None

    prod_resp = client.get("/onboarding/status", headers={"X-API-Key": "sk-telco-xxxx"})
    assert prod_resp.status_code == 401
    assert "Invalid API Key" in prod_resp.json()["detail"]
