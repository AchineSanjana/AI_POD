"""Session token authentication for company accounts using signed JWTs.

Provides:
- Short-lived JWT session token issuance upon login.
- Token decoding and expiration verification.
- FastAPI dependency for authenticating account-level endpoints (/me, /keys/regenerate).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Header, HTTPException, Request, status

from src.accounts.storage import get_account_by_id

logger = logging.getLogger(__name__)

# Minimum 32-byte secret key to satisfy RFC 7518 Section 3.2 HMAC SHA-256 requirement
DEFAULT_JWT_SECRET = (
    "ai_pod_default_secret_key_change_in_production_min32bytes_long_key_string"
)
JWT_SECRET = (
    os.environ.get("JWT_SECRET_KEY")
    or os.environ.get("SESSION_SECRET")
    or DEFAULT_JWT_SECRET
)
JWT_ALGORITHM = "HS256"
DEFAULT_EXPIRY_SECONDS = int(os.environ.get("SESSION_EXPIRY_SECONDS", "3600"))


def create_session_token(
    account_id: str,
    tenant_id: str,
    email: str,
    expires_in: int = DEFAULT_EXPIRY_SECONDS,
) -> str:
    """Create a signed JWT session token for an authenticated company account."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": account_id,
        "account_id": account_id,
        "tenant_id": tenant_id,
        "email": email.strip().lower(),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_session_token(token: str) -> dict[str, Any]:
    """Verify and decode a signed JWT session token.

    Raises:
        HTTPException: If the token is invalid, expired, or malformed.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Please log in again.",
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid session token: {exc}",
        )


def get_current_account(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
) -> dict[str, Any]:
    """FastAPI dependency resolving the authenticated company account.

    Accepts session token from either:
    - Authorization: Bearer <token>
    - X-Session-Token: <token>
    """
    token: str | None = None

    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]

    if not token and x_session_token:
        token = x_session_token.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Session token required. "
                "Provide 'Authorization: Bearer <token>' header."
            ),
        )

    payload = verify_session_token(token)
    account_id = payload.get("account_id") or payload.get("sub")
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session token payload",
        )

    account_record = get_account_by_id(account_id)
    if not account_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found or inactive",
        )

    account_data = dict(account_record)
    account_data["account_id"] = account_id
    return account_data
