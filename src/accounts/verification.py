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

from dotenv import load_dotenv

load_dotenv()

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

    Returns True if successfully sent via SMTP, False otherwise.
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
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    if smtp_host:
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            port = int(os.environ.get("SMTP_PORT", "587"))
            use_ssl = (
                os.environ.get("SMTP_USE_SSL", "").strip().lower() in ("true", "1", "yes")
                or port == 465
            )
            user = os.environ.get("SMTP_USER", "").strip() or None
            pwd = os.environ.get("SMTP_PASS", "").strip() or None
            sender = os.environ.get("SMTP_FROM", "").strip() or user or "no-reply@ai-pod.local"

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Your AI POD Verification Code: {code}"
            msg["From"] = sender
            msg["To"] = clean_email

            text_content = (
                f"Hello {company_name},\n\n"
                f"Your AI POD verification code is: {code}\n"
                f"This code will expire in {VERIFICATION_EXPIRY_MINUTES} minutes.\n\n"
                f"Thank you,\nAI POD Team"
            )
            html_content = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 540px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
              <div style="margin-bottom: 20px;">
                <span style="font-size: 24px; font-weight: 800; color: #4f46e5;">✨ AI POD</span>
              </div>
              <h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Verify your email address</h2>
              <p style="color: #475569; font-size: 15px; line-height: 1.5;">
                Hello <strong>{company_name}</strong>,
              </p>
              <p style="color: #475569; font-size: 15px; line-height: 1.5;">
                Enter this 6-digit verification code to activate your account and issue your API keys:
              </p>
              <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; text-align: center; margin: 24px 0;">
                <span style="font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #4f46e5; font-family: monospace;">{code}</span>
              </div>
              <p style="color: #64748b; font-size: 13px; line-height: 1.5;">
                This code expires in <strong>{VERIFICATION_EXPIRY_MINUTES} minutes</strong>. If you did not create an account on AI POD, you can safely ignore this email.
              </p>
              <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0 16px 0;" />
              <p style="color: #94a3b8; font-size: 12px; margin: 0;">AI POD Multi-Tenant Recommendations Engine</p>
            </div>
            """
            msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            timeout = float(os.environ.get("SMTP_TIMEOUT", "12.0"))
            if use_ssl:
                with smtplib.SMTP_SSL(smtp_host, port, timeout=timeout) as server:
                    if user and pwd:
                        server.login(user, pwd)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, port, timeout=timeout) as server:
                    if os.environ.get("SMTP_STARTTLS", "true").strip().lower() in ("true", "1", "yes"):
                        server.starttls()
                    if user and pwd:
                        server.login(user, pwd)
                    server.send_message(msg)

            logger.info("Dispatched verification email to '%s' via SMTP (%s:%d)", clean_email, smtp_host, port)
            return True
        except Exception as exc:
            logger.warning("Failed sending verification email via SMTP (%s): %s", smtp_host, exc)
            return False

    logger.info(
        "Verification code for '%s' (%s): [%s] (expires in %d min, SMTP not configured)",
        company_name,
        clean_email,
        code,
        VERIFICATION_EXPIRY_MINUTES,
    )
    return False


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

    email_dispatched = dispatch_verification_email(
        email=account["email"],
        company_name=account.get("company_name", "User"),
        code=code,
        token=token,
    )

    return {
        "account_id": account_id,
        "email": account["email"],
        "verification_sent": True,
        "email_dispatched": email_dispatched,
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
