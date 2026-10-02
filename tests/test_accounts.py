"""Tests for company accounts, signup endpoint, secure storage, and credential privacy.

Verifies:
- POST /v1/accounts/signup creates a company account and returns account_id + tenant_id.
- Duplicate email is rejected with 409 Conflict.
- Weak password (< 8 chars) is rejected with 400 Bad Request.
- Invalid email format is rejected with 400 Bad Request.
- Password is NEVER stored or returned in plaintext in response, logs, or stored files.
- Stored password is a valid bcrypt hash that verifies with bcrypt.checkpw.
- Tenant ID is derived by slugifying company_name, with collision resolution suffixing.
- Step 15.2 pattern: works with both local YAML files and AWS SSM / Secrets Manager.
"""

from __future__ import annotations

import logging
import secrets

import pytest
import yaml
from fastapi.testclient import TestClient
from moto import mock_aws

from src.accounts.service import (
    hash_password,
    verify_password,
)
from src.accounts.storage import (
    get_account_by_email,
    get_account_by_id,
    get_account_by_tenant_id,
    list_accounts,
    save_account_record,
)
from src.api.app import app
from src.api.rate_limiter import SIGNUP_RATE_LIMITER


@pytest.fixture(autouse=True)
def reset_signup_rate_limiter():
    """Ensure signup rate limiter is reset between test runs."""
    SIGNUP_RATE_LIMITER.reset()
    yield
    SIGNUP_RATE_LIMITER.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def clean_accounts_file(tmp_path, monkeypatch):
    """Isolate accounts and auth storage to temporary files for local tests."""
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

    from src.api.auth import TENANT_AUTH_MAPPING, TENANT_KEY_RECORDS
    saved_records = dict(TENANT_KEY_RECORDS)
    saved_mapping = dict(TENANT_AUTH_MAPPING)

    yield temp_accounts

    TENANT_KEY_RECORDS.clear()
    TENANT_KEY_RECORDS.update(saved_records)
    TENANT_AUTH_MAPPING.clear()
    TENANT_AUTH_MAPPING.update(saved_mapping)



@pytest.fixture
def aws_env(monkeypatch):
    """Set standard AWS environment variables for moto tests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


def test_valid_signup_succeeds(client: TestClient, clean_accounts_file):
    """Confirm valid signup succeeds and returns account_id and tenant_id."""
    payload = {
        "company_name": "Acme Corp",
        "email": "dev@acme.com",
        "password": "StrongSecretPassword123!",
    }
    resp = client.post("/v1/accounts/signup", json=payload)
    assert resp.status_code == 201

    data = resp.json()
    assert "account_id" in data
    assert data["account_id"].startswith("acc_")
    assert data["tenant_id"] == "acme_corp"
    assert data["company_name"] == "Acme Corp"
    assert data["email"] == "dev@acme.com"
    assert data["email_verified"] is False
    assert "created_at" in data

    # Verify issued API keys and single-disclosure notice
    assert "private_key" in data
    assert data["private_key"].startswith("sk-acme_corp-")
    assert "public_key" in data
    assert data["public_key"].startswith("pk-acme_corp-")
    assert "note" in data
    assert "private key is shown here once" in data["note"].lower()

    # Verify password is NOT in response
    assert "password" not in data
    assert "password_hash" not in data
    assert "StrongSecretPassword123!" not in resp.text


def test_duplicate_email_rejected_with_409(client: TestClient, clean_accounts_file):
    """Confirm duplicate emails are rejected with a clear 409 Conflict."""
    payload1 = {
        "company_name": "Acme Corp",
        "email": "dev@acme.com",
        "password": "Password123!",
    }
    resp1 = client.post("/v1/accounts/signup", json=payload1)
    assert resp1.status_code == 201

    # Attempt signup with same email (exact match)
    payload2 = {
        "company_name": "Acme Corp 2",
        "email": "dev@acme.com",
        "password": "AnotherPassword456!",
    }
    resp2 = client.post("/v1/accounts/signup", json=payload2)
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["detail"]

    # Attempt signup with case variation (DEV@ACME.COM)
    payload3 = {
        "company_name": "Acme Corp 3",
        "email": "DEV@ACME.COM",
        "password": "AnotherPassword456!",
    }
    resp3 = client.post("/v1/accounts/signup", json=payload3)
    assert resp3.status_code == 409
    assert "already exists" in resp3.json()["detail"]


def test_weak_password_rejected(client: TestClient, clean_accounts_file):
    """Confirm password shorter than 8 characters is rejected with 400 Bad Request."""
    weak_passwords = ["123", "short", "1234567", ""]
    for pwd in weak_passwords:
        resp = client.post(
            "/v1/accounts/signup",
            json={
                "company_name": "Test Company",
                "email": f"user_{secrets.token_hex(3)}@test.com",
                "password": pwd,
            },
        )
        assert resp.status_code == 400
        assert "8 characters" in resp.json()["detail"]


def test_invalid_email_format_rejected(client: TestClient, clean_accounts_file):
    """Confirm invalid email formats are rejected with 400 Bad Request."""
    invalid_emails = ["not-an-email", "missing-at.com", "@missing-user.com", "user@"]
    for email in invalid_emails:
        resp = client.post(
            "/v1/accounts/signup",
            json={
                "company_name": "Test Company",
                "email": email,
                "password": "ValidPassword123!",
            },
        )
        assert resp.status_code == 400
        assert "Invalid email" in resp.json()["detail"]


def test_blank_company_name_rejected(client: TestClient, clean_accounts_file):
    """Confirm blank or whitespace company name is rejected with 400 Bad Request."""
    resp = client.post(
        "/v1/accounts/signup",
        json={
            "company_name": "   ",
            "email": "valid@company.com",
            "password": "ValidPassword123!",
        },
    )
    assert resp.status_code == 400
    assert "company_name" in resp.json()["detail"]


def test_password_never_stored_or_logged_or_returned(
    client: TestClient,
    clean_accounts_file,
    caplog,
):
    """Confirm plaintext password is never stored, returned, or logged anywhere."""
    sensitive_password = "SuperSecretUnstoredPassword999!"

    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/v1/accounts/signup",
            json={
                "company_name": "Secure Enterprises",
                "email": "admin@secure.org",
                "password": sensitive_password,
            },
        )
        assert resp.status_code == 201
        account_id = resp.json()["account_id"]

    # 1. Plaintext password is NOT in response body or JSON
    assert sensitive_password not in resp.text
    data = resp.json()
    assert "password" not in data
    assert "password_hash" not in data

    # 2. Plaintext password is NOT in logs
    assert sensitive_password not in caplog.text

    # 3. Check physical storage on disk
    assert clean_accounts_file.exists()
    file_content = clean_accounts_file.read_text(encoding="utf-8")

    # Plaintext password must NOT appear anywhere in the storage file
    assert sensitive_password not in file_content

    # The file must contain a valid bcrypt hash
    parsed_yaml = yaml.safe_load(file_content)
    account_record = parsed_yaml["accounts"][account_id]
    assert "password" not in account_record
    assert "password_hash" in account_record

    stored_hash = account_record["password_hash"]
    assert stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$")

    # Verify that the bcrypt hash actually verifies against the password
    assert verify_password(sensitive_password, stored_hash) is True
    assert verify_password("WrongPassword!", stored_hash) is False


def test_unique_tenant_id_generation_with_collisions(
    client: TestClient,
    clean_accounts_file,
):
    """Confirm that duplicate company names receive distinct, unique tenant_ids."""
    resp1 = client.post(
        "/v1/accounts/signup",
        json={
            "company_name": "Globex Corporation",
            "email": "user1@globex.com",
            "password": "Password123!",
        },
    )
    assert resp1.status_code == 201
    tenant_id_1 = resp1.json()["tenant_id"]
    assert tenant_id_1 == "globex_corporation"

    resp2 = client.post(
        "/v1/accounts/signup",
        json={
            "company_name": "Globex Corporation",
            "email": "user2@globex.com",
            "password": "Password123!",
        },
    )
    assert resp2.status_code == 201
    tenant_id_2 = resp2.json()["tenant_id"]

    # Must be distinct and start with base slug
    assert tenant_id_2 != tenant_id_1
    assert tenant_id_2.startswith("globex_corporation_")


def test_slugify_company_name_special_characters():
    """Verify slugification handles punctuation and non-alphanumeric chars."""
    from src.accounts.service import slugify_company_name

    assert slugify_company_name("Acme, Inc. & Co.") == "acme_inc_co"
    assert slugify_company_name("  Mega-Store 2026!  ") == "mega_store_2026"
    assert slugify_company_name("$$$") == "company"


@mock_aws
def test_accounts_secure_storage_aws_mode(aws_env, monkeypatch):
    """Verify storing and retrieving account records via AWS SSM (Step 15.2)."""
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


    account_id = "acc_test99"
    record = {
        "tenant_id": "cloud_corp",
        "company_name": "Cloud Corp",
        "email": "dev@cloudcorp.com",
        "password_hash": hash_password("CloudSecret123!"),
        "created_at": "2026-10-02T12:00:00Z",
        "email_verified": False,
    }

    # Save
    save_account_record(account_id, record)

    # Retrieve by ID
    loaded = get_account_by_id(account_id)
    assert loaded is not None
    assert loaded["company_name"] == "Cloud Corp"
    assert loaded["tenant_id"] == "cloud_corp"

    # Retrieve by Email
    found = get_account_by_email("DEV@CLOUDCORP.COM")
    assert found is not None
    acc_id, acc_rec = found
    assert acc_id == account_id
    assert acc_rec["company_name"] == "Cloud Corp"

    # Retrieve by Tenant ID
    found_tenant = get_account_by_tenant_id("cloud_corp")
    assert found_tenant is not None
    acc_id, _ = found_tenant
    assert acc_id == account_id

    # List
    all_accounts = list_accounts()
    assert account_id in all_accounts


def test_signup_immediately_produces_working_keys_without_restart(
    client: TestClient,
    clean_accounts_file,
):
    """Confirm signup immediately yields working keys without restart."""
    signup_payload = {

        "company_name": "Nexus Dynamics",
        "email": "ops@nexusdynamics.io",
        "password": "ProductionPassword2026!",
    }
    resp = client.post("/v1/accounts/signup", json=signup_payload)
    assert resp.status_code == 201

    body = resp.json()
    tenant_id = body["tenant_id"]
    sk = body["private_key"]
    pk = body["public_key"]

    assert tenant_id == "nexus_dynamics"
    assert sk.startswith("sk-nexus_dynamics-")
    assert pk.startswith("pk-nexus_dynamics-")
    assert "note" in body
    assert "shown here once" in body["note"].lower()

    # 1. Private key (sk-...) immediately works on protected endpoints without restart
    resp_priv = client.get(
        "/onboarding/status",
        headers={"X-API-Key": sk},
    )
    assert resp_priv.status_code == 200
    assert resp_priv.json()["tenant_id"] == "nexus_dynamics"

    # 2. Public key (pk-...) immediately works on permitted tracking endpoint
    track_event = {
        "customer_id": "cust_nexus_1",
        "session_id": "sess_nexus_1",
        "event_type": "view",
        "product_id": "prod_nexus_item",
    }
    resp_pub_track = client.post(
        "/v1/track",
        json=track_event,
        headers={"X-API-Key": pk},
    )
    assert resp_pub_track.status_code == 202
    assert resp_pub_track.json() == {"status": "accepted"}

    # 3. Public key is strictly restricted from administrative endpoints (403 Forbidden)
    resp_pub_forbidden = client.get(
        "/onboarding/status",
        headers={"X-API-Key": pk},
    )
    assert resp_pub_forbidden.status_code == 403
    assert "Forbidden" in resp_pub_forbidden.json()["detail"]

    # 4. Bogus key is rejected with 401 Unauthorized
    resp_bogus = client.get(
        "/onboarding/status",
        headers={"X-API-Key": "sk-bogus-key"},
    )
    assert resp_bogus.status_code == 401


def test_login_successful_and_wrong_password_rejected(
    client: TestClient,
    clean_accounts_file,
):
    """Test POST /v1/accounts/login with correct and incorrect credentials."""
    # 1. Sign up account
    signup_payload = {
        "company_name": "Auth Test Corp",
        "email": "security@authtest.com",
        "password": "CorrectPassword123!",
    }
    signup_resp = client.post("/v1/accounts/signup", json=signup_payload)
    assert signup_resp.status_code == 201
    account_id = signup_resp.json()["account_id"]
    tenant_id = signup_resp.json()["tenant_id"]

    # 2. Reject wrong password with 401 Unauthorized
    bad_login_resp = client.post(
        "/v1/accounts/login",
        json={"email": "security@authtest.com", "password": "WrongPassword999!"},
    )
    assert bad_login_resp.status_code == 401
    assert "Invalid email or password" in bad_login_resp.json()["detail"]

    # 3. Reject non-existent email with 401 Unauthorized
    missing_email_resp = client.post(
        "/v1/accounts/login",
        json={"email": "nonexistent@authtest.com", "password": "CorrectPassword123!"},
    )
    assert missing_email_resp.status_code == 401
    assert "Invalid email or password" in missing_email_resp.json()["detail"]

    # 4. Successful login returns short-lived JWT session token
    login_resp = client.post(
        "/v1/accounts/login",
        json={"email": "security@authtest.com", "password": "CorrectPassword123!"},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert "access_token" in login_data
    assert "session_token" in login_data
    assert login_data["token_type"] == "bearer"
    assert login_data["expires_in"] > 0
    assert login_data["account_id"] == account_id
    assert login_data["tenant_id"] == tenant_id

    # 5. Verify token is verifiable
    from src.accounts.session import verify_session_token

    payload = verify_session_token(login_data["access_token"])
    assert payload["account_id"] == account_id
    assert payload["tenant_id"] == tenant_id
    assert payload["email"] == "security@authtest.com"


def test_me_returns_company_name_tenant_id_and_public_key_only(
    client: TestClient,
    clean_accounts_file,
):
    """Test GET /v1/accounts/me returns only public info and NEVER private keys."""
    # 1. Sign up and login
    signup_payload = {
        "company_name": "Privacy First Ltd",
        "email": "admin@privacyfirst.com",
        "password": "PrivacyPassword2026!",
    }
    signup_resp = client.post("/v1/accounts/signup", json=signup_payload)
    assert signup_resp.status_code == 201
    orig_pk = signup_resp.json()["public_key"]
    orig_sk = signup_resp.json()["private_key"]

    login_resp = client.post(
        "/v1/accounts/login",
        json={"email": "admin@privacyfirst.com", "password": "PrivacyPassword2026!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # 2. Reject request without session token (401)
    unauth_resp = client.get("/v1/accounts/me")
    assert unauth_resp.status_code == 401

    # 3. Reject API key on /me (must use session token, not API key)
    api_key_resp = client.get("/v1/accounts/me", headers={"X-API-Key": orig_sk})
    assert api_key_resp.status_code == 401

    # 4. Authenticated request via Bearer header
    me_resp = client.get(
        "/v1/accounts/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()

    # Must return company_name, tenant_id, and public_key ONLY
    assert me_data["company_name"] == "Privacy First Ltd"
    assert me_data["tenant_id"] == "privacy_first_ltd"
    assert me_data["public_key"] == orig_pk

    # MUST NEVER expose private key or password
    assert "private_key" not in me_data
    assert "password" not in me_data
    assert "password_hash" not in me_data
    assert orig_sk not in me_resp.text

    # Also test X-Session-Token header support
    me_header_resp = client.get(
        "/v1/accounts/me",
        headers={"X-Session-Token": token},
    )
    assert me_header_resp.status_code == 200
    assert me_header_resp.json()["public_key"] == orig_pk


def test_keys_regenerate_invalidates_old_pair_and_issues_usable_new_pair(
    client: TestClient,
    clean_accounts_file,
):
    """Test /keys/regenerate invalidates old keys and issues usable new ones."""
    # 1. Sign up and obtain initial keys
    signup_payload = {
        "company_name": "Rotate Keys Inc",
        "email": "ops@rotatekeys.com",
        "password": "RotateSecretPass2026!",
    }
    signup_resp = client.post("/v1/accounts/signup", json=signup_payload)
    assert signup_resp.status_code == 201
    old_sk = signup_resp.json()["private_key"]
    old_pk = signup_resp.json()["public_key"]
    tenant_id = signup_resp.json()["tenant_id"]

    # Verify old keys initially work
    old_priv_check = client.get("/onboarding/status", headers={"X-API-Key": old_sk})
    assert old_priv_check.status_code == 200

    track_payload = {
        "customer_id": "c1",
        "session_id": "s1",
        "event_type": "view",
        "product_id": "prod_1",
    }
    old_pub_check = client.post(
        "/v1/track",
        json=track_payload,
        headers={"X-API-Key": old_pk},
    )
    assert old_pub_check.status_code == 202

    # 2. Log in to get session token
    login_resp = client.post(
        "/v1/accounts/login",
        json={"email": "ops@rotatekeys.com", "password": "RotateSecretPass2026!"},
    )
    assert login_resp.status_code == 200
    session_token = login_resp.json()["session_token"]

    # 3. Call /v1/accounts/keys/regenerate with session token
    regen_resp = client.post(
        "/v1/accounts/keys/regenerate",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert regen_resp.status_code == 200
    regen_data = regen_resp.json()

    new_sk = regen_data["private_key"]
    new_pk = regen_data["public_key"]
    assert regen_data["tenant_id"] == tenant_id
    assert "note" in regen_data
    assert "shown here once" in regen_data["note"].lower()

    # Ensure keys actually rotated
    assert new_sk != old_sk
    assert new_pk != old_pk
    assert new_sk.startswith(f"sk-{tenant_id}-")
    assert new_pk.startswith(f"pk-{tenant_id}-")

    # 4. Old keys MUST STOP WORKING IMMEDIATELY
    old_sk_fail = client.get("/onboarding/status", headers={"X-API-Key": old_sk})
    assert old_sk_fail.status_code == 401

    old_pk_fail = client.post(
        "/v1/track",
        json=track_payload,
        headers={"X-API-Key": old_pk},
    )
    assert old_pk_fail.status_code == 401

    # 5. New keys MUST WORK IMMEDIATELY
    new_sk_success = client.get("/onboarding/status", headers={"X-API-Key": new_sk})
    assert new_sk_success.status_code == 200
    assert new_sk_success.json()["tenant_id"] == tenant_id

    new_pk_success = client.post(
        "/v1/track",
        json=track_payload,
        headers={"X-API-Key": new_pk},
    )
    assert new_pk_success.status_code == 202

    # 6. /v1/accounts/me now reports the new public key and still no private key
    me_resp = client.get(
        "/v1/accounts/me",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["public_key"] == new_pk
    assert "private_key" not in me_resp.json()


def test_onboarding_portal_ui_contains_signup_login_and_key_management_elements(
    client: TestClient,
):
    """Verify /onboarding UI contains signup, login, disclosure, and dashboard."""
    resp = client.get("/onboarding")
    assert resp.status_code == 200
    html = resp.text

    # 1. Sign-up form elements calling /v1/accounts/signup
    assert 'id="signupCompanyName"' in html
    assert 'id="signupEmail"' in html
    assert 'id="signupPassword"' in html
    assert 'id="btnSignupSubmit"' in html
    assert "/v1/accounts/signup" in html

    # 2. One-time disclosure warning banner & copy buttons
    assert 'id="keysDisclosureBanner"' in html
    assert (
        "Single Disclosure Only" in html
        or "shown here strictly once" in html.lower()
    )
    assert 'id="disclosedPrivateKey"' in html
    assert 'id="disclosedPublicKey"' in html
    assert "copyTextToClipboard" in html

    # 3. Log-in form elements calling /v1/accounts/login
    assert 'id="loginEmail"' in html
    assert 'id="loginPassword"' in html
    assert 'id="btnLoginSubmit"' in html
    assert "/v1/accounts/login" in html

    # 4. Returning company dashboard showing public key & regenerate button
    assert 'id="authDashboardView"' in html
    assert 'id="dashPublicKey"' in html
    assert 'id="btnRegenerateKeys"' in html
    assert "/v1/accounts/keys/regenerate" in html
    assert "/v1/accounts/me" in html


def test_signup_ip_rate_limiting_rejects_burst_and_permits_different_ip(
    client: TestClient,
    clean_accounts_file,
):
    """Confirm repeated signups from same IP are rejected with 429; another IP works."""
    ip_a_headers = {"X-Forwarded-For": "198.51.100.10"}
    ip_b_headers = {"X-Forwarded-For": "203.0.113.88"}

    # 1. First 5 signups from IP A succeed (limit = 5)
    for i in range(5):
        resp = client.post(
            "/v1/accounts/signup",
            json={
                "company_name": f"Rate Limit Corp {i}",
                "email": f"dev_{i}@ratelimit{i}.com",
                "password": f"Password{i}Secure123!",
            },
            headers=ip_a_headers,
        )
        assert resp.status_code == 201

    # 2. 6th signup from IP A is REJECTED with 429 Too Many Requests
    excess_resp = client.post(
        "/v1/accounts/signup",
        json={
            "company_name": "Rate Limit Excess Corp",
            "email": "excess@ratelimit.com",
            "password": "PasswordExcessSecure123!",
        },
        headers=ip_a_headers,
    )
    assert excess_resp.status_code == 429
    assert "Too many requests from IP" in excess_resp.json()["detail"]
    assert "198.51.100.10" in excess_resp.json()["detail"]
    assert "Retry-After" in excess_resp.headers
    assert int(excess_resp.headers["Retry-After"]) > 0

    # 3. Signup from a DIFFERENT IP (IP B) is completely unaffected
    ip_b_resp = client.post(
        "/v1/accounts/signup",
        json={
            "company_name": "Independent Corp B",
            "email": "dev@independentb.com",
            "password": "PasswordBSecure123!",
        },
        headers=ip_b_headers,
    )
    assert ip_b_resp.status_code == 201
    assert ip_b_resp.json()["tenant_id"] == "independent_corp_b"

    # 4. Another signup from IP A is still rejected with 429
    still_blocked_resp = client.post(
        "/v1/accounts/signup",
        json={
            "company_name": "Still Blocked Corp",
            "email": "blocked@ratelimit.com",
            "password": "PasswordBlocked123!",
        },
        headers=ip_a_headers,
    )
    assert still_blocked_resp.status_code == 429



