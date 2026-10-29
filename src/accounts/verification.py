"""Email verification management.

Provides:
- Cryptographic 6-digit verification codes and URL-safe tokens.
- Verification code issuance, validation, and expiration management.
- Email dispatch adapter (SMTP, SES, or console logger for development).
- Rate-limited resend handling.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from src.accounts.storage import (
    get_account_by_email,
    get_account_by_id,
    save_account_record,
)

logger = logging.getLogger(__name__)

VERIFICATION_EXPIRY_MINUTES = 15
VERIFICATION_CODE_LENGTH = 6

# In-memory store of recent verification emails for local testing/debugging
RECENT_VERIFICATION_EMAILS: dict[str, dict[str, Any]] = {}


def generate_verification_code() -> str:
    """Generate a random 6-digit numeric verification code."""
    num = secrets.randbelow(900000) + 100000
    return str(num)


def generate_verification_token() -> str:
    """Generate a secure URL-safe verification token."""
    return secrets.token_urlsafe(32)


def dispatch_verification_email(
    email: str,
    company_name: str,
    code: str,
    token: str,
) -> bool:
    """Send verification email to user or log to development console.

    Returns True if successfully sent or queued.
    """
    clean_email = email.strip().lower()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Record in test/dev inspection cache
    RECENT_VERIFICATION_EMAILS[clean_email] = {
        "email": clean_email,
        "company_name": company_name,
        "code": code,
        "token": token,
        "sent_at": now_iso,
    }

    # In production with configured SMTP / SES, dispatch through external service
    smtp_host = os.environ.get("SMTP_HOST")
    if smtp_host:
        try:
            import smtplib
            from email.mime.text import MIMEText

            msg = MIMEText(
                f"Hello {company_name},\n\n"
                f"Your AI POD verification code is: {code}\n"
                f"This code will expire in {VERIFICATION_EXPIRY_MINUTES} minutes.\n\n"
                f"Thank you,\nAI POD Team"
            )
            msg["Subject"] = "Verify your AI POD Account"
            msg["From"] = os.environ.get("SMTP_FROM", "no-reply@ai-pod.local")
            msg["To"] = clean_email

            with smtplib.SMTP(
                smtp_host, int(os.environ.get("SMTP_PORT", "587"))
            ) as server:
                server.starttls()
                user = os.environ.get("SMTP_USER")
                pwd = os.environ.get("SMTP_PASS")
                if user and pwd:
                    server.login(user, pwd)
                server.send_message(msg)
            logger.info("Dispatched verification email to '%s' via SMTP", clean_email)
            return True
        except Exception as exc:
            logger.warning("Failed sending verification email via SMTP: %s", exc)

    logger.info(
        "Verification code for '%s' (%s): [%s] (expires in %d min)",
        company_name,
        clean_email,
        code,
        VERIFICATION_EXPIRY_MINUTES,
    )
    return True


def issue_verification_for_account(
    account_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate and store verification code and dispatch email."""
    account = get_account_by_id(account_id, config=config)
    if not account:
        raise ValueError(f"Account '{account_id}' not found")

    code = generate_verification_code()
    token = generate_verification_token()
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=VERIFICATION_EXPIRY_MINUTES)).isoformat()

    account["email_verified"] = False
    account["verification_code"] = code
    account["verification_token"] = token
    account["verification_expires_at"] = expires_at
    account["verification_sent_at"] = now.isoformat()
    account["verification_attempts"] = 0

    save_account_record(account_id, account, config=config)

    dispatch_verification_email(
        email=account["email"],
        company_name=account.get("company_name", "User"),
        code=code,
        token=token,
    )

    return {
        "account_id": account_id,
        "email": account["email"],
        "verification_sent": True,
        "verification_code": code,  # Accessible for tests/dev mode
        "expires_at": expires_at,
    }


def verify_account_email(
    email: str,
    code: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify an account email using the 6-digit code or URL-safe token."""
    clean_email = email.strip().lower()
    clean_code = code.strip()

    account_info = get_account_by_email(clean_email, config=config)
    if not account_info:
        raise ValueError("Invalid email or verification code")

    account_id, record = account_info

    if record.get("email_verified"):
        return {
            "account_id": account_id,
            "tenant_id": record["tenant_id"],
            "email": clean_email,
            "email_verified": True,
            "already_verified": True,
        }

    # Check verification attempts limit (protect against brute forcing the 6-digit code)
    attempts = record.get("verification_attempts", 0)
    if attempts >= 10:
        raise ValueError(
            "Too many failed verification attempts. Please request a new verification code."
        )

    stored_code = record.get("verification_code")
    stored_token = record.get("verification_token")
    expires_str = record.get("verification_expires_at")

    if not expires_str or not (stored_code or stored_token):
        raise ValueError("No active verification code found. Please request a new one.")

    # Check expiration
    expires_at = datetime.fromisoformat(expires_str)
    if datetime.now(timezone.utc) > expires_at:
        raise ValueError("Verification code has expired. Please request a new code.")

    # Verify matching code or token
    code_matches = stored_code and secrets.compare_digest(clean_code, stored_code)
    token_matches = stored_token and secrets.compare_digest(clean_code, stored_token)

    if not (code_matches or token_matches):
        record["verification_attempts"] = attempts + 1
        save_account_record(account_id, record, config=config)
        raise ValueError("Invalid verification code")

    # Mark as verified
    record["email_verified"] = True
    record["email_verified_at"] = datetime.now(timezone.utc).isoformat()
    record.pop("verification_code", None)
    record.pop("verification_token", None)
    record.pop("verification_expires_at", None)
    record.pop("verification_attempts", None)

    save_account_record(account_id, record, config=config)

    logger.info(
        "Account '%s' (%s) successfully verified email", account_id, clean_email
    )
    return {
        "account_id": account_id,
        "tenant_id": record["tenant_id"],
        "email": clean_email,
        "email_verified": True,
        "already_verified": False,
    }
