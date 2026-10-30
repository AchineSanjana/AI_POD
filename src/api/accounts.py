"""Company Accounts API endpoints.

Provides:
- POST /v1/accounts/signup: Register a company account, hash password with bcrypt,
  generate a unique tenant_id, and issue verification code.
- POST /v1/accounts/verify-email: Verify account email with 6-digit code or token.
- POST /v1/accounts/resend-verification: Resend verification code.
- POST /v1/accounts/login: Authenticate company account, enforce lockout protection,
  check email verification, and issue session JWT or MFA challenge ticket.
- POST /v1/accounts/login/mfa: Complete 2FA login with TOTP or backup code.
- POST /v1/accounts/mfa/setup: Generate TOTP secret and otpauth URI.
- POST /v1/accounts/mfa/enable: Activate TOTP MFA and generate backup codes.
- POST /v1/accounts/mfa/disable: Disable TOTP MFA.
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
    AccountLockedError,
    AuthenticationFailedError,
    DuplicateEmailError,
    EmailNotVerifiedError,
    InvalidCompanyNameError,
    InvalidEmailError,
    InvalidMfaCodeError,
    WeakPasswordError,
    disable_account_mfa,
    enable_account_mfa,
    get_account_me_profile,
    login_company_account,
    login_mfa_verify,
    regenerate_account_keys,
    resend_email_verification,
    setup_account_mfa,
    signup_company_account,
    verify_email_for_account,
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
    """

    account_id: str = Field(..., description="Unique account ID (e.g. acc_8f2k1x)")
    tenant_id: str = Field(..., description="Provisioned tenant identifier")
    company_name: str = Field(..., description="Company name")
    email: str = Field(..., description="Contact email")
    created_at: str = Field(..., description="ISO-8601 creation timestamp")
    email_verified: bool = Field(False, description="Verification status of the email")
    verification_sent: bool = Field(
        True, description="Whether email verification code was sent"
    )
    verification_code: str | None = Field(
        None, description="Verification code (accessible in test/dev environments)"
    )
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


class VerifyEmailRequest(BaseModel):
    """Payload to verify an email address."""

    email: str = Field(..., description="Account email address")
    code: str = Field(..., description="6-digit verification code or token")


class VerifyEmailResponse(BaseModel):
    """Response returned upon email verification."""

    account_id: str = Field(..., description="Account identifier")
    tenant_id: str = Field(..., description="Tenant identifier")
    email: str = Field(..., description="Verified email address")
    email_verified: bool = Field(..., description="Verification status")
    already_verified: bool = Field(
        False, description="Whether email was already verified"
    )
    message: str = Field("Email successfully verified.", description="Status message")


class ResendVerificationRequest(BaseModel):
    """Payload to request resending verification code."""

    email: str = Field(..., description="Account email address")


class ResendVerificationResponse(BaseModel):
    """Response returned upon resending verification code."""

    email: str = Field(..., description="Account email address")
    verification_sent: bool = Field(..., description="Dispatch status")
    verification_code: str | None = Field(
        None, description="Dispatched code in dev/test mode"
    )
    message: str = Field(..., description="Status message")


class AccountLoginRequest(BaseModel):
    """Payload for company account login."""

    email: str = Field(..., description="Account email address")
    password: str = Field(..., description="Account password")


class AccountLoginResponse(BaseModel):
    """Session authentication token response or MFA challenge ticket."""

    access_token: str | None = Field(None, description="Short-lived JWT session token")
    session_token: str | None = Field(None, description="Short-lived JWT session token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token validity in seconds")
    account_id: str = Field(..., description="Account identifier")
    tenant_id: str = Field(..., description="Associated tenant identifier")
    mfa_required: bool = Field(
        default=False, description="Whether 2FA code is required"
    )
    mfa_ticket: str | None = Field(
        default=None, description="Temporary ticket for 2FA challenge"
    )


class MfaLoginRequest(BaseModel):
    """Payload for completing two-factor login."""

    mfa_ticket: str = Field(
        ..., description="Temporary challenge ticket issued by /v1/accounts/login"
    )
    code: str = Field(..., description="6-digit TOTP code or backup recovery code")


class MfaSetupResponse(BaseModel):
    """Response containing MFA secret and QR / URI information."""

    account_id: str = Field(..., description="Account identifier")
    secret: str = Field(..., description="Base32 TOTP secret key")
    otpauth_url: str = Field(
        ..., description="Standard otpauth:// URI for authenticator apps"
    )


class MfaEnableRequest(BaseModel):
    """Payload to confirm TOTP code and enable MFA."""

    code: str = Field(..., description="6-digit TOTP code from authenticator app")


class MfaEnableResponse(BaseModel):
    """Response returned when MFA is successfully activated."""

    account_id: str = Field(..., description="Account identifier")
    status: str = Field("mfa_enabled", description="MFA status")
    mfa_enabled: bool = Field(True, description="Whether MFA is enabled")
    backup_codes: list[str] = Field(..., description="Single-use backup recovery codes")
    warning: str = Field(..., description="Advisory regarding backup recovery codes")


class MfaDisableRequest(BaseModel):
    """Payload to disable MFA."""

    password: str = Field(..., description="Account password")
    code: str = Field(
        ..., description="Current 6-digit TOTP code or backup recovery code"
    )


class MfaDisableResponse(BaseModel):
    """Response returned when MFA is disabled."""

    account_id: str = Field(..., description="Account identifier")
    status: str = Field("mfa_disabled", description="MFA status")
    mfa_enabled: bool = Field(False, description="Whether MFA is enabled")


class AccountMeResponse(BaseModel):
    """Public account profile representation."""

    company_name: str = Field(..., description="Display or trading name of the company")
    tenant_id: str = Field(..., description="Associated tenant identifier")
    public_key: str = Field(
        ...,
        description="Public API key (pk-...). Permitted for client-side SDK tracking.",
    )
    email_verified: bool = Field(
        default=False, description="Whether email has been verified"
    )
    mfa_enabled: bool = Field(default=False, description="Whether 2FA / MFA is enabled")
    role: str | None = Field(default="user", description="Account role")
    is_admin: bool | None = Field(
        default=False, description="Whether account has admin privileges"
    )


class AccountKeysRegenerateResponse(BaseModel):
    """Key regeneration response containing new credentials."""

    account_id: str = Field(..., description="Account identifier")
    tenant_id: str = Field(..., description="Tenant identifier")
    private_key: str = Field(
        ...,
        description="Newly generated private API key (sk-...). Disclosed strictly once.",
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
        "assigns a unique slugified tenant_id, issues an email verification code, "
        "and automatically issues private and public API keys."
    ),
)
def signup(payload: AccountSignupRequest) -> AccountSignupResponse:
    """Create a new company account, provision tenant_id, and issue API keys."""
    try:
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InvalidEmailError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except WeakPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during account signup: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account",
        )


@router.post(
    "/verify-email",
    status_code=status.HTTP_200_OK,
    response_model=VerifyEmailResponse,
    summary="Verify account email",
    description="Validates the 6-digit verification code or token and marks email as verified.",
)
def verify_email(payload: VerifyEmailRequest) -> VerifyEmailResponse:
    """Verify company account email address."""
    try:
        result = verify_email_for_account(email=payload.email, code=payload.code)
        return VerifyEmailResponse(**result)
    except AccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during email verification: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify email",
        )


@router.post(
    "/resend-verification",
    status_code=status.HTTP_200_OK,
    response_model=ResendVerificationResponse,
    summary="Resend verification email",
    description="Dispatches a fresh 6-digit email verification code.",
)
def resend_verification(
    payload: ResendVerificationRequest,
) -> ResendVerificationResponse:
    """Resend email verification code."""
    try:
        result = resend_email_verification(email=payload.email)
        return ResendVerificationResponse(**result)
    except Exception as exc:
        logger.exception("Unexpected error resending verification: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resend verification email",
        )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=AccountLoginResponse,
    summary="Log in to company account",
    description=(
        "Authenticates company credentials with brute force lockout protection. "
        "Returns a session token or an MFA challenge ticket if 2FA is active."
    ),
)
def login(payload: AccountLoginRequest) -> AccountLoginResponse:
    """Authenticate company account credentials and return session token or MFA challenge."""
    try:
        result = login_company_account(
            email=payload.email,
            password=payload.password,
        )
        return AccountLoginResponse(**result)
    except AccountLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=str(exc),
        )
    except EmailNotVerifiedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
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


@router.post(
    "/login/mfa",
    status_code=status.HTTP_200_OK,
    response_model=AccountLoginResponse,
    summary="Complete 2FA login",
    description="Validates MFA challenge ticket and TOTP code or backup code, issuing session token.",
)
def login_mfa(payload: MfaLoginRequest) -> AccountLoginResponse:
    """Verify second-factor code and issue signed session JWT."""
    try:
        result = login_mfa_verify(
            mfa_ticket=payload.mfa_ticket,
            code=payload.code,
        )
        return AccountLoginResponse(**result)
    except InvalidMfaCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )
    except AuthenticationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during MFA verification: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify 2FA code",
        )


@router.post(
    "/mfa/setup",
    status_code=status.HTTP_200_OK,
    response_model=MfaSetupResponse,
    summary="Initiate MFA setup",
    description="Generates a base32 TOTP secret and otpauth URL for authenticator apps.",
)
def mfa_setup(
    current_account: dict[str, Any] = Depends(get_current_account),
) -> MfaSetupResponse:
    """Generate TOTP secret for the authenticated company account."""
    try:
        result = setup_account_mfa(account_id=current_account["account_id"])
        return MfaSetupResponse(**result)
    except AccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error setting up MFA: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate MFA setup",
        )


@router.post(
    "/mfa/enable",
    status_code=status.HTTP_200_OK,
    response_model=MfaEnableResponse,
    summary="Enable MFA on account",
    description="Verifies TOTP code against pending secret, enables MFA, and returns backup codes.",
)
def mfa_enable(
    payload: MfaEnableRequest,
    current_account: dict[str, Any] = Depends(get_current_account),
) -> MfaEnableResponse:
    """Activate MFA and return single-use recovery backup codes."""
    try:
        result = enable_account_mfa(
            account_id=current_account["account_id"],
            code=payload.code,
        )
        return MfaEnableResponse(**result)
    except InvalidMfaCodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except AccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error enabling MFA: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enable MFA",
        )


@router.post(
    "/mfa/disable",
    status_code=status.HTTP_200_OK,
    response_model=MfaDisableResponse,
    summary="Disable MFA on account",
    description="Verifies password and current TOTP/backup code, then disables MFA.",
)
def mfa_disable(
    payload: MfaDisableRequest,
    current_account: dict[str, Any] = Depends(get_current_account),
) -> MfaDisableResponse:
    """Deactivate MFA on account."""
    try:
        result = disable_account_mfa(
            account_id=current_account["account_id"],
            password=payload.password,
            code=payload.code,
        )
        return MfaDisableResponse(**result)
    except (InvalidMfaCodeError, AuthenticationFailedError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except AccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error disabling MFA: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disable MFA",
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
        profile["email_verified"] = current_account.get("email_verified", False)
        profile["mfa_enabled"] = current_account.get("mfa_enabled", False)
        if "role" in current_account:
            profile["role"] = current_account["role"]
        if "is_admin" in current_account:
            profile["is_admin"] = current_account["is_admin"]
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
