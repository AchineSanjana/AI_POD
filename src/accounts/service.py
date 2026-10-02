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
import re
import secrets
import string
from datetime import datetime, timezone
from typing import Any

import bcrypt

from src.accounts.storage import (
    get_account_by_email,
    get_account_by_id,
    get_accounts_records,
    save_account_record,
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
    }

    save_account_record(account_id, record, config=cfg)

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

    Raises:
        AuthenticationFailedError: If credentials do not match.
    """
    from src.accounts.session import DEFAULT_EXPIRY_SECONDS, create_session_token

    clean_email = (email or "").strip().lower()
    if not clean_email or not password:
        raise AuthenticationFailedError("Invalid email or password")

    cfg = config or load_config()
    account_info = get_account_by_email(clean_email, config=cfg)
    if account_info is None:
        raise AuthenticationFailedError("Invalid email or password")

    account_id, record = account_info
    stored_hash = record.get("password_hash", "")
    if not verify_password(password, stored_hash):
        raise AuthenticationFailedError("Invalid email or password")

    tenant_id = record["tenant_id"]
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


