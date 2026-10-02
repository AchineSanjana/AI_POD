"""Company Accounts domain package.

Provides secure storage, account lifecycle, bcrypt hashing, and FastAPI router.
"""

from src.accounts.service import (
    AccountError,
    DuplicateEmailError,
    InvalidCompanyNameError,
    InvalidEmailError,
    WeakPasswordError,
    hash_password,
    signup_company_account,
    validate_email_format,
    validate_password_strength,
    verify_password,
)
from src.accounts.storage import (
    get_account_by_email,
    get_account_by_id,
    get_account_by_tenant_id,
    get_accounts_records,
    list_accounts,
    save_account_record,
)

__all__ = [
    "AccountError",
    "DuplicateEmailError",
    "InvalidCompanyNameError",
    "InvalidEmailError",
    "WeakPasswordError",
    "get_account_by_email",
    "get_account_by_id",
    "get_account_by_tenant_id",
    "get_accounts_records",
    "hash_password",
    "list_accounts",
    "save_account_record",
    "signup_company_account",
    "validate_email_format",
    "validate_password_strength",
    "verify_password",
]
