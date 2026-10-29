"""Account management service logic.

Handles:
- Validation for company names, email format, and password strength (8+ chars).
- Safe password hashing with bcrypt.
- Unique tenant_id generation by slugifying company names with collision resolution.
- Unique account_id generation (acc_xxxxxx).
- Account creation and persistence.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt

from src.accounts.storage import (
    get_account_by_email,
    get_account_by_id,
    get_accounts_records,
    save_account_record,
)
from src.accounts.totp import (
    generate_backup_codes,
    generate_totp_secret,
    get_totp_uri,
    hash_backup_code,
    verify_and_consume_backup_code,
    verify_totp_code,
)
from src.accounts.verification import (
    issue_verification_for_account,
    verify_account_email,
)
from src.utils.config import get_tenant_auth_records, load_config
from src.utils.key_manager import (
    get_tenant_public_key,
    issue_tenant_keys,
    regenerate_tenant_keys,
)

logger = logging.getLogger(__name__)


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
ACCOUNT_ID_ALPHABET = string.ascii_lowercase + string.digits


class AccountError(Exception):
    """Base exception for account operations."""


class WeakPasswordError(AccountError):
    """Raised when password does not meet minimum strength requirements."""


class InvalidEmailError(AccountError):
    """Raised when email format is invalid."""


class DuplicateEmailError(AccountError):
    """Raised when an account with the specified email already exists."""


class AuthenticationFailedError(AccountError):
    """Raised when account credentials (email/password) are invalid."""


class InvalidCompanyNameError(AccountError):
    """Raised when company name is empty or invalid."""


class AccountLockedError(AccountError):
    """Raised when account is temporarily locked due to too many failed login attempts."""


class EmailNotVerifiedError(AccountError):
    """Raised when email verification is required before login."""


class InvalidMfaCodeError(AccountError):
    """Raised when 2FA TOTP code or backup code is invalid."""


def validate_company_name(company_name: str) -> str:
    """Validate that company_name is a non-empty string."""
    clean = (company_name or "").strip()
    if not clean:
        raise InvalidCompanyNameError("company_name cannot be blank")
    return clean


def validate_email_format(email: str) -> str:
    """Validate email address format and return normalized lowercase email."""
    clean = (email or "").strip().lower()
    if not clean or not EMAIL_REGEX.match(clean):
        raise InvalidEmailError(f"Invalid email format: '{clean}'")
    return clean


def validate_password_strength(password: str) -> None:
    """Validate password strength. Minimum check: 8+ characters."""
    if not password or len(password) < 8:
        raise WeakPasswordError("Password must be at least 8 characters long")


def hash_password(password: str) -> str:
    """Securely hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def slugify_company_name(name: str) -> str:
    """Convert company name to an alphanumeric slug with underscores.

    Example:
        'Acme Corp' -> 'acme_corp'
        'Foo & Bar, Inc.' -> 'foo_bar_inc'
    """
    clean = name.strip().lower()
    slug = SLUG_PATTERN.sub("_", clean).strip("_")
    if not slug:
        return "company"
    return slug


def get_all_existing_tenant_ids(config: dict[str, Any] | None = None) -> set[str]:
    """Collect all registered tenant IDs across config, auth keys, and accounts."""
    cfg = config or load_config()
    existing: set[str] = set()

    # 1. Tenancies declared in config['tenants']
    if isinstance(cfg, dict):
        cfg_tenants = cfg.get("tenants", {})
        if isinstance(cfg_tenants, dict):
            existing.update(cfg_tenants.keys())

    # 2. Tenancies with issued keys in tenants_auth
    try:
        auth_records = get_tenant_auth_records(cfg)
        for rec in auth_records.values():
            if isinstance(rec, dict) and "tenant_id" in rec:
                existing.add(rec["tenant_id"])
    except Exception as exc:
        logger.debug("Failed querying tenant auth records: %s", exc)

    # 3. Tenancies owned by existing accounts
    try:
        account_records = get_accounts_records(cfg)
        for rec in account_records.values():
            if isinstance(rec, dict) and "tenant_id" in rec:
                existing.add(rec["tenant_id"])
    except Exception as exc:
        logger.debug("Failed querying existing accounts: %s", exc)

    return existing


def generate_unique_tenant_id(
    company_name: str,
    config: dict[str, Any] | None = None,
) -> str:
    """Generate a unique tenant_id from company name.

    Slugifies the name. If the slug already exists, appends a short random suffix.
    """
    existing_tenants = get_all_existing_tenant_ids(config)
    base_slug = slugify_company_name(company_name)

    if base_slug not in existing_tenants:
        return base_slug

    # Collision resolution: append a short 4-character random suffix
    while True:
        suffix = "".join(secrets.choice(ACCOUNT_ID_ALPHABET) for _ in range(4))
        candidate = f"{base_slug}_{suffix}"
        if candidate not in existing_tenants:
            return candidate


def generate_account_id(existing_ids: set[str] | None = None) -> str:
    """Generate a unique account identifier with 'acc_' prefix (e.g. 'acc_8f2k1x')."""
    seen = existing_ids or set()
    while True:
        suffix = "".join(secrets.choice(ACCOUNT_ID_ALPHABET) for _ in range(6))
        account_id = f"acc_{suffix}"
        if account_id not in seen:
            return account_id


def signup_company_account(
    company_name: str,
    email: str,
    password: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute account signup workflow.

    1. Validate company_name, email format, and password strength (8+ chars).
    2. Reject duplicate email with DuplicateEmailError.
    3. Hash password using bcrypt.
    4. Generate unique tenant_id from company_name (with collision suffix if needed).
    5. Persist account record.
    6. Return account info without any password or hash.
    """
    clean_company = validate_company_name(company_name)
    clean_email = validate_email_format(email)
    validate_password_strength(password)

    cfg = config or load_config()

    # Reject duplicate emails
    existing = get_account_by_email(clean_email, config=cfg)
    if existing is not None:
        raise DuplicateEmailError(f"Account with email '{clean_email}' already exists")

    # Hash password (plaintext password is never retained or returned)
    hashed_pwd = hash_password(password)

    # Unique IDs
    accounts = get_accounts_records(cfg)
    account_id = generate_account_id(existing_ids=set(accounts.keys()))
    tenant_id = generate_unique_tenant_id(clean_company, config=cfg)

    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "tenant_id": tenant_id,
        "company_name": clean_company,
        "email": clean_email,
        "password_hash": hashed_pwd,
        "created_at": now_iso,
        "email_verified": False,
        "failed_login_attempts": 0,
        "mfa_enabled": False,
    }

    save_account_record(account_id, record, config=cfg)

    # Issue email verification code / token
    verif_info = issue_verification_for_account(account_id, config=cfg)

    # Automatically issue private (sk-...) and public (pk-...) tenant API keys.
    # Note: The private key is shown here once upon signup and will not be
    # retrievable in plaintext again from any API endpoint or storage (consistent
    # with how modern API platforms handle secret keys). Frontend Step 24.4
    # must prompt the user to copy and securely save this key immediately.
    key_bundle = issue_tenant_keys(tenant_id=tenant_id, config=cfg)
    sk = key_bundle["sk"]
    pk = key_bundle["pk"]

    logger.info(
        "Created company account '%s' (tenant_id='%s') and issued keys for '%s'",
        account_id,
        tenant_id,
        clean_email,
    )

    security_note = (
        "The private key is shown here once and will not be retrievable in "
        "plaintext again. Please store it securely."
    )

    return {
        "account_id": account_id,
        "tenant_id": tenant_id,
        "company_name": clean_company,
        "email": clean_email,
        "created_at": now_iso,
        "email_verified": False,
        "verification_sent": True,
        "verification_code": verif_info.get("verification_code"),
        "private_key": sk,
        "public_key": pk,
        "note": security_note,
        "warning": security_note,
    }


def login_company_account(
    email: str,
    password: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Authenticate company account credentials and issue session JWT.

    Protections:
    - Account-level lockout: 5 failed attempts locks account for 15 minutes.
    - Optional Email Verification enforcement.
    - Two-factor authentication (MFA): returns mfa_ticket if MFA is enabled.

    Raises:
        AccountLockedError: If account is temporarily locked.
        EmailNotVerifiedError: If email verification is strictly required and missing.
        AuthenticationFailedError: If credentials do not match.
    """
    from src.accounts.session import (
        DEFAULT_EXPIRY_SECONDS,
        create_mfa_ticket,
        create_session_token,
    )

    clean_email = (email or "").strip().lower()
    if not clean_email or not password:
        raise AuthenticationFailedError("Invalid email or password")

    cfg = config or load_config()
    account_info = get_account_by_email(clean_email, config=cfg)
    if account_info is None:
        raise AuthenticationFailedError("Invalid email or password")

    account_id, record = account_info

    # 1. Account lockout check
    now = datetime.now(timezone.utc)
    locked_until_str = record.get("locked_until")
    if locked_until_str:
        try:
            locked_until = datetime.fromisoformat(locked_until_str)
            if now < locked_until:
                remaining_sec = int((locked_until - now).total_seconds())
                remaining_min = max(1, (remaining_sec + 59) // 60)
                raise AccountLockedError(
                    f"Account is temporarily locked due to too many failed login attempts. "
                    f"Please try again in {remaining_min} minutes."
                )
            else:
                record["failed_login_attempts"] = 0
                record.pop("locked_until", None)
        except AccountLockedError:
            raise
        except Exception:
            pass

    # 2. Verify password hash
    stored_hash = record.get("password_hash", "")
    if not verify_password(password, stored_hash):
        failed_attempts = record.get("failed_login_attempts", 0) + 1
        record["failed_login_attempts"] = failed_attempts
        if failed_attempts >= 5:
            lock_expiry = (now + timedelta(minutes=15)).isoformat()
            record["locked_until"] = lock_expiry
            save_account_record(account_id, record, config=cfg)
            raise AccountLockedError(
                "Account is temporarily locked due to too many failed login attempts. "
                "Please try again in 15 minutes."
            )
        save_account_record(account_id, record, config=cfg)
        raise AuthenticationFailedError("Invalid email or password")

    # Reset failed attempts upon successful password check
    if record.get("failed_login_attempts", 0) > 0 or "locked_until" in record:
        record["failed_login_attempts"] = 0
        record.pop("locked_until", None)
        save_account_record(account_id, record, config=cfg)

    # 3. Email verification enforcement check
    enforce_verif = (
        os.environ.get("ENFORCE_EMAIL_VERIFICATION", "false").lower() == "true"
    )
    if enforce_verif and not record.get("email_verified", False):
        raise EmailNotVerifiedError(
            "Email has not been verified. Please verify your email before logging in."
        )

    tenant_id = record["tenant_id"]

    # 4. Multi-Factor Authentication (MFA) check
    if record.get("mfa_enabled", False):
        mfa_ticket = create_mfa_ticket(
            account_id=account_id,
            tenant_id=tenant_id,
            email=clean_email,
            expires_in=300,
        )
        logger.info("Issued MFA challenge ticket for account '%s'", account_id)
        return {
            "mfa_required": True,
            "mfa_ticket": mfa_ticket,
            "expires_in": 300,
            "account_id": account_id,
            "tenant_id": tenant_id,
        }

    token = create_session_token(
        account_id=account_id,
        tenant_id=tenant_id,
        email=clean_email,
        expires_in=DEFAULT_EXPIRY_SECONDS,
    )

    logger.info("Account login successful for '%s' (%s)", account_id, clean_email)
    return {
        "access_token": token,
        "session_token": token,
        "token_type": "bearer",
        "expires_in": DEFAULT_EXPIRY_SECONDS,
        "account_id": account_id,
        "tenant_id": tenant_id,
        "mfa_required": False,
    }


def verify_email_for_account(
    email: str,
    code: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify company account email address using verification code or token."""
    cfg = config or load_config()
    try:
        return verify_account_email(email=email, code=code, config=cfg)
    except ValueError as exc:
        raise AccountError(str(exc))


def resend_email_verification(
    email: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resend email verification code."""
    clean_email = (email or "").strip().lower()
    cfg = config or load_config()
    account_info = get_account_by_email(clean_email, config=cfg)
    if not account_info:
        # Avoid account enumeration: return success-like message even if email not found
        return {
            "email": clean_email,
            "verification_sent": True,
            "message": "If an account with this email exists, a verification code has been dispatched.",
        }

    account_id, record = account_info
    if record.get("email_verified"):
        return {
            "email": clean_email,
            "verification_sent": False,
            "message": "This email is already verified.",
        }

    info = issue_verification_for_account(account_id, config=cfg)
    return {
        "email": clean_email,
        "verification_sent": True,
        "verification_code": info.get("verification_code"),
        "message": "Verification code has been dispatched.",
    }


def setup_account_mfa(
    account_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Initiate TOTP MFA setup by generating a secret and otpauth URI."""
    cfg = config or load_config()
    record = get_account_by_id(account_id, config=cfg)
    if not record:
        raise AccountError("Account not found")

    secret = generate_totp_secret()
    record["mfa_pending_secret"] = secret
    save_account_record(account_id, record, config=cfg)

    otpauth_url = get_totp_uri(secret, email=record.get("email", ""), issuer="AI POD")
    return {
        "account_id": account_id,
        "secret": secret,
        "otpauth_url": otpauth_url,
    }


def enable_account_mfa(
    account_id: str,
    code: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify code against pending secret and activate MFA on account."""
    cfg = config or load_config()
    record = get_account_by_id(account_id, config=cfg)
    if not record:
        raise AccountError("Account not found")

    pending_secret = record.get("mfa_pending_secret")
    if not pending_secret:
        raise AccountError("No MFA setup in progress. Call /mfa/setup first.")

    if not verify_totp_code(pending_secret, code):
        raise InvalidMfaCodeError("Invalid 2FA verification code")

    # Generate 8 backup recovery codes
    backup_codes = generate_backup_codes(8)
    hashed_backup_codes = [hash_backup_code(c) for c in backup_codes]

    record["mfa_enabled"] = True
    record["mfa_secret"] = pending_secret
    record["mfa_backup_codes"] = hashed_backup_codes
    record.pop("mfa_pending_secret", None)
    save_account_record(account_id, record, config=cfg)

    logger.info("MFA enabled for account '%s'", account_id)
    return {
        "account_id": account_id,
        "status": "mfa_enabled",
        "mfa_enabled": True,
        "backup_codes": backup_codes,
        "warning": "Store backup recovery codes in a safe place. They will not be displayed again.",
    }


def disable_account_mfa(
    account_id: str,
    password: str,
    code: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Disable MFA after verifying account password and TOTP or backup code."""
    cfg = config or load_config()
    record = get_account_by_id(account_id, config=cfg)
    if not record:
        raise AccountError("Account not found")

    if not record.get("mfa_enabled"):
        raise AccountError("MFA is not enabled on this account")

    stored_hash = record.get("password_hash", "")
    if not verify_password(password, stored_hash):
        raise AuthenticationFailedError("Invalid account password")

    secret = record.get("mfa_secret", "")
    valid_totp = secret and verify_totp_code(secret, code)
    valid_backup, _ = verify_and_consume_backup_code(
        code, record.get("mfa_backup_codes", [])
    )

    if not (valid_totp or valid_backup):
        raise InvalidMfaCodeError("Invalid 2FA code or backup code")

    record["mfa_enabled"] = False
    record.pop("mfa_secret", None)
    record.pop("mfa_backup_codes", None)
    save_account_record(account_id, record, config=cfg)

    logger.info("MFA disabled for account '%s'", account_id)
    return {
        "account_id": account_id,
        "status": "mfa_disabled",
        "mfa_enabled": False,
    }


def login_mfa_verify(
    mfa_ticket: str,
    code: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate MFA challenge ticket and second factor code, returning full session token."""
    from src.accounts.session import (
        DEFAULT_EXPIRY_SECONDS,
        create_session_token,
        verify_mfa_ticket,
    )

    payload = verify_mfa_ticket(mfa_ticket)
    account_id = payload["account_id"]
    tenant_id = payload["tenant_id"]
    email = payload["email"]

    cfg = config or load_config()
    record = get_account_by_id(account_id, config=cfg)
    if not record:
        raise AuthenticationFailedError("Account not found")

    secret = record.get("mfa_secret", "")
    valid_totp = secret and verify_totp_code(secret, code)
    valid_backup, remaining_backup = verify_and_consume_backup_code(
        code, record.get("mfa_backup_codes", [])
    )

    if not (valid_totp or valid_backup):
        raise InvalidMfaCodeError("Invalid 2FA verification code or backup code")

    if valid_backup:
        record["mfa_backup_codes"] = remaining_backup
        save_account_record(account_id, record, config=cfg)
        logger.info("Backup recovery code used for account '%s'", account_id)

    token = create_session_token(
        account_id=account_id,
        tenant_id=tenant_id,
        email=email,
        expires_in=DEFAULT_EXPIRY_SECONDS,
    )

    return {
        "access_token": token,
        "session_token": token,
        "token_type": "bearer",
        "expires_in": DEFAULT_EXPIRY_SECONDS,
        "account_id": account_id,
        "tenant_id": tenant_id,
    }


def regenerate_account_keys(
    account_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invalidate all existing tenant keys and issue a fresh pair.

    Returns the new key pair once, matching signup behavior.
    """
    cfg = config or load_config()
    record = get_account_by_id(account_id, config=cfg)
    if not record:
        raise AccountError("Account not found")

    tenant_id = record["tenant_id"]
    new_bundle = regenerate_tenant_keys(tenant_id, config=cfg)
    sk = new_bundle["sk"]
    pk = new_bundle["pk"]

    logger.info(
        "Regenerated API keys for tenant '%s' (account '%s')",
        tenant_id,
        account_id,
    )
    security_note = (
        "The private key is shown here once and will not be retrievable in "
        "plaintext again. Please store it securely."
    )
    return {
        "account_id": account_id,
        "tenant_id": tenant_id,
        "private_key": sk,
        "public_key": pk,
        "note": security_note,
        "warning": security_note,
    }


def get_account_me_profile(
    account_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retrieve public profile for authenticated account.

    Returns company_name, tenant_id, and public_key ONLY. Never returns private_key.
    """
    cfg = config or load_config()
    record = get_account_by_id(account_id, config=cfg)
    if not record:
        raise AccountError("Account not found")

    tenant_id = record["tenant_id"]
    public_key = get_tenant_public_key(tenant_id, config=cfg) or f"pk-{tenant_id}-xxxx"

    return {
        "company_name": record.get("company_name", ""),
        "tenant_id": tenant_id,
        "public_key": public_key,
    }
