"""Secure storage for company accounts.

Follows the Step 15.2 / Step 18.1 local-file-vs-AWS-secure-storage pattern:
- Local Mode (backend != 's3'): Persists to config/accounts.local.yaml (git-ignored).
- AWS Mode (backend == 's3'): Persists to AWS SSM Parameter Store (/ai_pod/accounts)
  or AWS Secrets Manager.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from src.utils.config import load_config, resolve_path

logger = logging.getLogger(__name__)

LOCAL_ACCOUNTS_FILE = "config/accounts.local.yaml"
EXAMPLE_ACCOUNTS_FILE = "config/accounts.example.yaml"
DEFAULT_ACCOUNTS_SSM_PARAM = "/ai_pod/accounts"


def _get_storage_context(
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Determine the active storage backend and storage configuration."""
    cfg = config or load_config()
    storage_cfg = cfg.get("storage", {}) if isinstance(cfg, dict) else {}
    backend = os.environ.get(
        "STORAGE_BACKEND", storage_cfg.get("backend", "local")
    ).strip().lower()
    return backend, storage_cfg


def _resolve_accounts_path(path_val: str | Any) -> Path:
    p = Path(path_val)
    if p.is_absolute():
        return p
    return resolve_path(p)


def get_accounts_records(
    config: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Retrieve all company accounts records from secure storage.

    Returns:
        Dict mapping account_id -> account record dictionary:
        {
            "acc_8f2k1x": {
                "tenant_id": "acme_corp",
                "company_name": "Acme Corp",
                "email": "dev@acme.com",
                "password_hash": "<bcrypt hash>",
                "created_at": "2026-10-05T10:00:00Z",
                "email_verified": False
            }
        }
    """
    backend, storage_cfg = _get_storage_context(config)

    if backend == "s3":
        import boto3

        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or storage_cfg.get("region")
            or "us-east-1"
        )
        secret_name = (
            os.environ.get("ACCOUNTS_SECRET_NAME")
            or storage_cfg.get("accounts_secret_name")
        )

        if secret_name:
            sm = boto3.client("secretsmanager", region_name=region)
            try:
                resp = sm.get_secret_value(SecretId=secret_name)
                data = json.loads(resp.get("SecretString", "{}"))
                if isinstance(data, dict):
                    accounts_map = data.get("accounts", data)
                    if isinstance(accounts_map, dict):
                        return accounts_map
            except Exception as exc:
                logger.debug(
                    "Failed loading accounts secret '%s': %s", secret_name, exc
                )
                return {}
        else:
            param_name = (
                os.environ.get("ACCOUNTS_SSM_PARAM")
                or os.environ.get("ACCOUNTS_PARAM")
                or storage_cfg.get("accounts_ssm_param")
                or DEFAULT_ACCOUNTS_SSM_PARAM
            )
            ssm = boto3.client("ssm", region_name=region)
            try:
                resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
                data = json.loads(resp["Parameter"]["Value"])
                if isinstance(data, dict):
                    accounts_map = data.get("accounts", data)
                    if isinstance(accounts_map, dict):
                        return accounts_map
            except Exception as exc:
                logger.debug(
                    "Failed loading accounts SSM parameter '%s': %s", param_name, exc
                )
                return {}
        return {}

    # Local mode: read config/accounts.local.yaml
    local_path = _resolve_accounts_path(LOCAL_ACCOUNTS_FILE)
    if local_path.exists():
        try:
            with open(local_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                accounts_map = data.get("accounts", data)
                if isinstance(accounts_map, dict):
                    return accounts_map
        except Exception as exc:
            logger.debug("Failed reading local accounts file: %s", exc)

    # In-memory config override (e.g. from tests)
    if config and isinstance(config, dict) and "accounts" in config:
        if isinstance(config["accounts"], dict):
            return config["accounts"]

    return {}



def list_accounts(
    config: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return all accounts indexed by account_id."""
    return get_accounts_records(config)


def get_account_by_id(
    account_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Look up an account record by account_id."""
    accounts = get_accounts_records(config)
    return accounts.get(account_id.strip())


def get_account_by_email(
    email: str,
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Look up an account record by case-insensitive email.

    Returns (account_id, record) or None.
    """
    clean_email = email.strip().lower()
    accounts = get_accounts_records(config)
    for acc_id, record in accounts.items():
        if not isinstance(record, dict):
            continue
        rec_email = record.get("email", "").strip().lower()
        if rec_email == clean_email:
            return acc_id, record
    return None


def get_account_by_tenant_id(
    tenant_id: str,
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Look up an account record that owns the given tenant_id.

    Returns (account_id, record) or None.
    """
    clean_tenant = tenant_id.strip()
    accounts = get_accounts_records(config)
    for acc_id, record in accounts.items():
        if not isinstance(record, dict):
            continue
        if record.get("tenant_id", "").strip() == clean_tenant:
            return acc_id, record
    return None


def save_account_record(
    account_id: str,
    record: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an account record to secure storage.

    Args:
        account_id: Unique account identifier (e.g. 'acc_8f2k1x').
        record: Account metadata dictionary.
        config: Optional loaded configuration dictionary.

    Returns:
        The stored account record dictionary.
    """
    clean_account_id = account_id.strip()
    if not clean_account_id:
        raise ValueError("account_id cannot be blank")

    backend, storage_cfg = _get_storage_context(config)

    if backend == "s3":
        import boto3

        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or storage_cfg.get("region")
            or "us-east-1"
        )
        secret_name = (
            os.environ.get("ACCOUNTS_SECRET_NAME")
            or storage_cfg.get("accounts_secret_name")
        )

        if secret_name:
            sm = boto3.client("secretsmanager", region_name=region)
            try:
                resp = sm.get_secret_value(SecretId=secret_name)
                data = json.loads(resp.get("SecretString", "{}"))
            except Exception:
                data = {}
            if "accounts" not in data or not isinstance(data["accounts"], dict):
                data = {"accounts": data}
            data["accounts"][clean_account_id] = record
            sm.put_secret_value(SecretId=secret_name, SecretString=json.dumps(data))
        else:
            param_name = (
                os.environ.get("ACCOUNTS_SSM_PARAM")
                or os.environ.get("ACCOUNTS_PARAM")
                or storage_cfg.get("accounts_ssm_param")
                or DEFAULT_ACCOUNTS_SSM_PARAM
            )
            ssm = boto3.client("ssm", region_name=region)
            try:
                resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
                data = json.loads(resp["Parameter"]["Value"])
            except Exception:
                data = {}
            if "accounts" not in data or not isinstance(data["accounts"], dict):
                data = {"accounts": data}
            data["accounts"][clean_account_id] = record
            ssm.put_parameter(
                Name=param_name,
                Value=json.dumps(data),
                Type="SecureString",
                Overwrite=True,
            )
        logger.info("Persisted account '%s' to AWS secure storage", clean_account_id)
    else:
        # Local mode: persist to config/accounts.local.yaml
        local_path = _resolve_accounts_path(LOCAL_ACCOUNTS_FILE)
        data: dict[str, Any] = {}
        if local_path.exists():
            try:
                with open(local_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                data = {}

        if "accounts" not in data or not isinstance(data["accounts"], dict):
            data = {"accounts": {}}

        data["accounts"][clean_account_id] = record
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        logger.info("Persisted account '%s' to '%s'", clean_account_id, local_path)

    return record
