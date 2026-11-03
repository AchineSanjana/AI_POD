"""Tests for hardened authentication: Email verification, TOTP MFA, brute-force lockout, and production key safety."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.accounts.totp import (
    generate_totp_code,
)
from src.accounts.verification import RECENT_VERIFICATION_EMAILS
from src.api.app import app
from src.api.rate_limiter import EMAIL_RESEND_RATE_LIMITER, SIGNUP_RATE_LIMITER


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    SIGNUP_RATE_LIMITER.reset()
    EMAIL_RESEND_RATE_LIMITER.reset()
    yield
    SIGNUP_RATE_LIMITER.reset()
    EMAIL_RESEND_RATE_LIMITER.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def clean_accounts(tmp_path, monkeypatch):
    temp_accounts = tmp_path / "accounts.local.yaml"
    temp_auth = tmp_path / "tenants_auth.local.yaml"

    monkeypatch.setattr("src.accounts.storage.LOCAL_ACCOUNTS_FILE", str(temp_accounts))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("ENFORCE_EMAIL_VERIFICATION", "false")

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
    # Security: verification_code must NOT be returned in API response
    assert "verification_code" not in data
    assert "code" not in data
    assert "token" not in data

    # Verify code was dispatched to in-memory store
    record = RECENT_VERIFICATION_EMAILS.get("dev@securecorp.com")
    assert record is not None
    code = record["code"]
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
    assert "verification_code" not in signup_resp.json()
    code = RECENT_VERIFICATION_EMAILS["verify@testcorp.com"]["code"]

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
    # Security: verification_code must NOT be returned in API response
    assert "verification_code" not in data
    assert "code" not in data
    assert "token" not in data

    code = RECENT_VERIFICATION_EMAILS["resend@testcorp.com"]["code"]
    assert len(code) == 6
    assert code.isdigit()


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
    assert signup_resp.status_code == 201
    assert "verification_code" not in signup_resp.json()
    code = RECENT_VERIFICATION_EMAILS["strict@testcorp.com"]["code"]

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


def test_security_responses_contain_no_verification_code(client: TestClient, clean_accounts):
    """Verify POST /signup, /resend-verification, and /verify-email strip code and token."""
    # 1. Signup
    signup_payload = {
        "company_name": "NoLeak Corp",
        "email": "noleak@testcorp.com",
        "password": "Password123!",
    }
    signup_resp = client.post("/v1/accounts/signup", json=signup_payload)
    assert signup_resp.status_code == 201
    signup_data = signup_resp.json()
    assert "verification_code" not in signup_data
    assert "code" not in signup_data
    assert "token" not in signup_data

    # Code is only in RECENT_VERIFICATION_EMAILS
    code = RECENT_VERIFICATION_EMAILS["noleak@testcorp.com"]["code"]
    assert code and len(code) == 6

    # 2. Resend
    EMAIL_RESEND_RATE_LIMITER.reset()
    resend_resp = client.post(
        "/v1/accounts/resend-verification",
        json={"email": "noleak@testcorp.com"},
    )
    assert resend_resp.status_code == 200
    resend_data = resend_resp.json()
    assert "verification_code" not in resend_data
    assert "code" not in resend_data
    assert "token" not in resend_data

    # 3. Verify
    new_code = RECENT_VERIFICATION_EMAILS["noleak@testcorp.com"]["code"]
    verify_resp = client.post(
        "/v1/accounts/verify-email",
        json={"email": "noleak@testcorp.com", "code": new_code},
    )
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()
    assert "verification_code" not in verify_data
    assert "code" not in verify_data
    assert "token" not in verify_data


def test_resend_verification_rate_limiting_60s(client: TestClient, clean_accounts):
    """Verify max 1 resend per 60s per email returns 429 with Retry-After header."""
    signup_payload = {
        "company_name": "Rate Corp",
        "email": "ratelimit@testcorp.com",
        "password": "Password123!",
    }
    client.post("/v1/accounts/signup", json=signup_payload)

    # First resend succeeds
    resp1 = client.post(
        "/v1/accounts/resend-verification",
        json={"email": "ratelimit@testcorp.com"},
    )
    assert resp1.status_code == 200

    # Immediate second resend is rate-limited
    resp2 = client.post(
        "/v1/accounts/resend-verification",
        json={"email": "ratelimit@testcorp.com"},
    )
    assert resp2.status_code == 429
    assert "Retry-After" in resp2.headers
    retry_after = int(resp2.headers["Retry-After"])
    assert 1 <= retry_after <= 60
    assert "too many" in resp2.json()["detail"].lower()


def test_resend_verification_rate_limiter_hourly():
    """Verify dual window limiter enforces max 5 resends per hour."""
    limiter = EMAIL_RESEND_RATE_LIMITER
    limiter.reset()

    email = "window@testcorp.com"
    base_time = 1000.0

    # 5 resends spaced 65s apart (allowed by 60s rule)
    for i in range(5):
        allowed, retry = limiter.check(email, now=base_time + (i * 65))
        assert allowed is True
        assert retry == 0

    # 6th attempt within the hour window (325s from start) -> rejected by 5/hour rule
    allowed, retry = limiter.check(email, now=base_time + 325)
    assert allowed is False
    # Next available should be base_time + 3600
    expected_retry = 3600 - 325
    assert retry == expected_retry

    # After 1 hour has elapsed, it succeeds
    allowed, retry = limiter.check(email, now=base_time + 3601)
    assert allowed is True
    assert retry == 0


def test_dev_last_verification_endpoint(client: TestClient, clean_accounts, monkeypatch):
    """GET /v1/accounts/dev/last-verification returns code in dev, 404 in production."""
    signup_payload = {
        "company_name": "Dev Check Corp",
        "email": "devcheck@testcorp.com",
        "password": "Password123!",
    }
    client.post("/v1/accounts/signup", json=signup_payload)

    # 1. Dev mode succeeds
    monkeypatch.setenv("ENV", "development")
    dev_resp = client.get("/v1/accounts/dev/last-verification?email=devcheck@testcorp.com")
    assert dev_resp.status_code == 200
    data = dev_resp.json()
    assert data["email"] == "devcheck@testcorp.com"
    assert len(data["code"]) == 6
    assert data["code"].isdigit()
    assert "sent_at" in data

    # 2. Unknown email returns 404
    unknown_resp = client.get("/v1/accounts/dev/last-verification?email=unknown@testcorp.com")
    assert unknown_resp.status_code == 404

    # 3. Production mode returns 404 for security
    monkeypatch.setenv("ENV", "production")
    prod_resp = client.get("/v1/accounts/dev/last-verification?email=devcheck@testcorp.com")
    assert prod_resp.status_code == 404

    # 4. AI_POD_ENV=prod also blocks
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("AI_POD_ENV", "prod")
    prod2_resp = client.get("/v1/accounts/dev/last-verification?email=devcheck@testcorp.com")
    assert prod2_resp.status_code == 404


def test_startup_logging_email_delivery(monkeypatch, caplog):
    """Lifespan logs SMTP vs CONSOLE ONLY, and logs ERROR when production has no SMTP_HOST."""
    import logging
    from src.api.app import lifespan

    # Case 1: SMTP configured
    monkeypatch.setenv("SMTP_HOST", "smtp.sendgrid.net")
    monkeypatch.setenv("ENV", "development")
    caplog.clear()
    with caplog.at_level(logging.INFO):
        import asyncio
        async def run_lifespan():
            async with lifespan(app):
                pass
        asyncio.run(run_lifespan())
    assert any("Email delivery: SMTP via smtp.sendgrid.net" in r.message for r in caplog.records)

    # Case 2: No SMTP in development -> CONSOLE ONLY info log
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("ENFORCE_EMAIL_VERIFICATION", "false")
    monkeypatch.setenv("ENV", "development")
    caplog.clear()
    with caplog.at_level(logging.INFO):
        asyncio.run(run_lifespan())
    assert any("Email delivery: CONSOLE ONLY (SMTP_HOST not set)" in r.message for r in caplog.records)

    # Case 3: No SMTP in production -> ERROR log
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("ENFORCE_EMAIL_VERIFICATION", "false")
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "testing-jwt-secret")
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        asyncio.run(run_lifespan())
    assert any("Production environment has no SMTP_HOST configured" in r.message for r in caplog.records)
