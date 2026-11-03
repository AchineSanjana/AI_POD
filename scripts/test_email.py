#!/usr/bin/env python3
"""CLI utility to test SMTP email delivery using active environment configuration.

Usage:
    python scripts/test_email.py --to user@example.com
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root .env is loaded
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def send_test_email(to_address: str) -> bool:
    """Send a test email using active SMTP configuration.

    Prints success or the exact SMTP exception. Returns True on success, False on failure.
    """
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    if not smtp_host:
        print("[ERROR] SMTP_HOST is not set in the environment or .env file.")
        print("Please configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, and SMTP_FROM.")
        return False

    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = (
        os.environ.get("SMTP_USE_SSL", "").strip().lower() in ("true", "1", "yes")
        or port == 465
    )
    user = os.environ.get("SMTP_USER", "").strip() or None
    pwd = os.environ.get("SMTP_PASS", "").strip() or None
    sender = os.environ.get("SMTP_FROM", "").strip() or user or "no-reply@ai-pod.local"

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"Connecting to SMTP host '{smtp_host}:{port}' (SSL={use_ssl}, From='{sender}')...")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[AI POD] SMTP Email Verification Test ({now_utc})"
    msg["From"] = sender
    msg["To"] = to_address.strip()

    text_body = (
        f"This is a test verification email from AI POD.\n\n"
        f"Timestamp: {now_utc}\n"
        f"SMTP Host: {smtp_host}:{port}\n"
        f"Sender: {sender}\n"
        f"Recipient: {to_address}\n\n"
        f"If you received this message, your SMTP configuration is operational."
    )
    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 10px;">
        <h2 style="color: #2563eb; margin-top: 0;">AI POD &mdash; SMTP Test</h2>
        <p>This is a test email confirming your outgoing email configuration is working.</p>
        <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
            <tr><td style="padding: 6px 0; color: #64748b; font-size: 13px;">Host:</td><td style="font-size: 13px;">{smtp_host}:{port}</td></tr>
            <tr><td style="padding: 6px 0; color: #64748b; font-size: 13px;">From:</td><td style="font-size: 13px;">{sender}</td></tr>
            <tr><td style="padding: 6px 0; color: #64748b; font-size: 13px;">To:</td><td style="font-size: 13px;">{to_address}</td></tr>
            <tr><td style="padding: 6px 0; color: #64748b; font-size: 13px;">Timestamp:</td><td style="font-size: 13px;">{now_utc}</td></tr>
        </table>
    </div>
    """
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_host, port, timeout=15) as server:
                if user and pwd:
                    server.login(user, pwd)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, port, timeout=15) as server:
                server.ehlo()
                if server.has_extn("starttls"):
                    server.starttls()
                    server.ehlo()
                if user and pwd:
                    server.login(user, pwd)
                server.send_message(msg)

        print(f"[SUCCESS] Test email successfully delivered to '{to_address}' via {smtp_host}:{port}.")
        return True
    except smtplib.SMTPAuthenticationError as exc:
        print(f"[ERROR] SMTPAuthenticationError: {exc.smtp_code} - {exc.smtp_error.decode('utf-8', errors='replace') if isinstance(exc.smtp_error, bytes) else exc.smtp_error}")
        return False
    except smtplib.SMTPConnectError as exc:
        print(f"[ERROR] SMTPConnectError: {exc}")
        return False
    except smtplib.SMTPException as exc:
        print(f"[ERROR] SMTPException ({exc.__class__.__name__}): {exc}")
        return False
    except Exception as exc:
        print(f"[ERROR] Exception ({exc.__class__.__name__}): {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test AI POD outgoing SMTP email configuration.")
    parser.add_argument("--to", required=True, help="Recipient email address for test message")
    args = parser.parse_args()

    success = send_test_email(args.to)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

