"""Company Accounts API endpoints.

Provides:
- POST /v1/accounts/signup: Register a company account, hash password with bcrypt,
  and generate a unique tenant_id.
- POST /v1/accounts/login: Authenticate company account and issue session JWT.
- GET /v1/accounts/me: Retrieve public account profile (authenticated by session token).
- POST /v1/accounts/keys/regenerate: Invalidate existing keys and issue fresh pair.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.accounts.service import (
    AccountError,
    AuthenticationFailedError,
    DuplicateEmailError,
    InvalidCompanyNameError,
    InvalidEmailError,
    WeakPasswordError,
    get_account_me_profile,
    login_company_account,
    regenerate_account_keys,
    signup_company_account,
)
from src.accounts.session import get_current_account
from src.api.rate_limiter import check_ip_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
)


class AccountSignupRequest(BaseModel):
    """Payload for company account registration."""

    company_name: str = Field(..., description="Display or trading name of the company")
    email: str = Field(..., description="Developer / company contact email")
    password: str = Field(..., description="Password (at least 8 characters)")


class AccountSignupResponse(BaseModel):
    """Public representation of a created company account.

    Never contains password or password hash.
    Contains both private (sk-...) and public (pk-...) API keys.

    CRITICAL SECURITY NOTICE:
    The private key is disclosed in plaintext strictly once upon signup.
    It will never be displayed or retrievable in plaintext again through any
    endpoint or storage record. The frontend UI (Step 24.4) must present this
    key to the user with a prompt to copy and securely save it immediately.
    """

    account_id: str = Field(..., description="Unique account ID (e.g. acc_8f2k1x)")
    tenant_id: str = Field(..., description="Provisioned tenant identifier")
    company_name: str = Field(..., description="Company name")
    email: str = Field(..., description="Contact email")
    created_at: str = Field(..., description="ISO-8601 creation timestamp")
    email_verified: bool = Field(False, description="Verification status of the email")
    private_key: str = Field(
        ...,
        description=(
            "Private API key (sk-...). Disclosed strictly once upon signup; "
            "not retrievable in plaintext again."
        ),
    )
    public_key: str = Field(
        ...,
        description="Public API key (pk-...). Permitted for client-side SDK tracking.",
    )
    note: str = Field(
        default=(
            "The private key is shown here once and will not be retrievable in "
            "plaintext again. Please store it securely."
        ),
        description="Security advisory regarding secret key disclosure",
    )
    warning: str = Field(
        default=(
            "The private key is shown here once and will not be retrievable in "
            "plaintext again. Please store it securely."
        ),
        description="Security advisory regarding secret key disclosure",
    )


class AccountLoginRequest(BaseModel):
    """Payload for company account login."""

    email: str = Field(..., description="Account email address")
    password: str = Field(..., description="Account password")


class AccountLoginResponse(BaseModel):
    """Session authentication token response."""

    access_token: str = Field(..., description="Short-lived JWT session token")
    session_token: str = Field(..., description="Short-lived JWT session token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token validity in seconds")
    account_id: str = Field(..., description="Account identifier")
    tenant_id: str = Field(..., description="Associated tenant identifier")


class AccountMeResponse(BaseModel):
    """Public account profile representation.

    CRITICAL SECURITY NOTICE:
    Returns company_name, tenant_id, and public_key ONLY.
    Never returns private_key or password.
    """

    company_name: str = Field(..., description="Display or trading name of the company")
    tenant_id: str = Field(..., description="Associated tenant identifier")
    public_key: str = Field(
        ...,
        description="Public API key (pk-...). Permitted for client-side SDK tracking.",
    )


class AccountKeysRegenerateResponse(BaseModel):
    """Key regeneration response containing new credentials.

    CRITICAL SECURITY NOTICE:
    Returns newly generated private and public key pair. The old pair is
    invalidated immediately. The private key is disclosed strictly once.
    """

    account_id: str = Field(..., description="Account identifier")
    tenant_id: str = Field(..., description="Tenant identifier")
    private_key: str = Field(
        ...,
        description=(
            "Newly generated private API key (sk-...). Disclosed strictly once."
        ),
    )
    public_key: str = Field(
        ...,
        description="Newly generated public API key (pk-...).",
    )
    note: str = Field(
        default=(
            "The private key is shown here once and will not be retrievable in "
            "plaintext again. Please store it securely."
        ),
        description="Security advisory regarding secret key disclosure",
    )
    warning: str = Field(
        default=(
            "The private key is shown here once and will not be retrievable in "
            "plaintext again. Please store it securely."
        ),
        description="Security advisory regarding secret key disclosure",
    )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=AccountSignupResponse,
    dependencies=[Depends(check_ip_rate_limit(scope="signup"))],
    summary="Sign up a new company account",
    description=(
        "Registers a new company account, hashes password using bcrypt, "
        "assigns a unique slugified tenant_id, and automatically issues "
        "private and public API keys. The private key is revealed once."
    ),
)
def signup(payload: AccountSignupRequest) -> AccountSignupResponse:
    """Create a new company account, provision tenant_id, and issue API keys.

    Note: The returned private_key is shown here strictly once and cannot
    be retrieved in plaintext again.
    """
    try:
        # Note: Password is never logged or exposed
        logger.info(
            "Processing signup request for company '%s' (email: '%s')",
            payload.company_name,
            payload.email,
        )
        result = signup_company_account(
            company_name=payload.company_name,
            email=payload.email,
            password=payload.password,
        )
        return AccountSignupResponse(**result)
    except InvalidCompanyNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except InvalidEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except WeakPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected error during account signup: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account",
        )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=AccountLoginResponse,
    summary="Log in to company account",
    description=(
        "Authenticates company credentials and issues a signed JWT session token."
    ),
)
def login(payload: AccountLoginRequest) -> AccountLoginResponse:
    """Authenticate company account credentials and return session token."""
    try:
        result = login_company_account(
            email=payload.email,
            password=payload.password,
        )
        return AccountLoginResponse(**result)
    except AuthenticationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected error during account login: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to authenticate account",
        )


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=AccountMeResponse,
    summary="Get authenticated company profile",
    description=(
        "Retrieves company_name, tenant_id, and public_key for the authenticated "
        "account session. Never exposes private keys or passwords."
    ),
)
def get_me(
    current_account: dict[str, Any] = Depends(get_current_account),
) -> AccountMeResponse:
    """Return public company profile without private keys."""
    try:
        profile = get_account_me_profile(account_id=current_account["account_id"])
        return AccountMeResponse(**profile)
    except AccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected error fetching account profile: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve profile",
        )


@router.post(
    "/keys/regenerate",
    status_code=status.HTTP_200_OK,
    response_model=AccountKeysRegenerateResponse,
    summary="Regenerate API keys",
    description=(
        "Invalidates the existing API key pair immediately and issues a brand new "
        "private and public key pair. Returns the private key strictly once."
    ),
)
def regenerate_keys(
    current_account: dict[str, Any] = Depends(get_current_account),
) -> AccountKeysRegenerateResponse:
    """Invalidate existing keys and issue a fresh pair for the authenticated tenant."""
    try:
        result = regenerate_account_keys(account_id=current_account["account_id"])
        return AccountKeysRegenerateResponse(**result)
    except AccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected error regenerating keys: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate keys",
        )
