"""Utility functions for issuing, managing, and persisting tenant API keys.

Supports both private and public API key types with created_at timestamps.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import yaml

from src.utils.config import load_config, resolve_path


def issue_tenant_keys(
    tenant_id: str,
    private_key: str | None = None,
    public_key: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Issue both a private and a public API key for a tenant at once.

    Args:
        tenant_id: Unique tenant identifier.
        private_key: Optional custom private key. Defaults to
            'sk-{tenant_id}-{random_hex}'.
        public_key: Optional custom public key. Defaults to
            'pk-{tenant_id}-{random_hex}'.
        config: Optional loaded configuration dictionary.

    Returns:
        Dictionary containing the issued key records and details.
    """
    clean_tenant = tenant_id.strip()
    if not clean_tenant:
        raise ValueError("tenant_id cannot be blank")

    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    now_iso = datetime.now(timezone.utc).isoformat()

    # Generate keys if not provided
    sk = (
        private_key.strip()
        if private_key
        else f"sk-{clean_tenant}-{secrets.token_hex(6)}"
    )
    pk = (
        public_key.strip()
        if public_key
        else f"pk-{clean_tenant}-{secrets.token_hex(6)}"
    )

    private_record = {
        "tenant_id": clean_tenant,
        "key_type": "private",
        "created_at": now_iso,
    }
    public_record = {
        "tenant_id": clean_tenant,
        "key_type": "public",
        "created_at": now_iso,
    }

    # Persist keys according to storage backend
    storage_cfg = config.get("storage", {})
    backend = os.environ.get(
        "STORAGE_BACKEND", storage_cfg.get("backend", "local")
    ).strip().lower()

    if backend == "s3":
        import boto3

        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or storage_cfg.get("region")
            or "us-east-1"
        )
        secret_name = (
            os.environ.get("TENANTS_AUTH_SECRET_NAME")
            or storage_cfg.get("tenants_auth_secret_name")
        )

        if secret_name:
            sm = boto3.client("secretsmanager", region_name=region)
            try:
                resp = sm.get_secret_value(SecretId=secret_name)
                data = json.loads(resp.get("SecretString", "{}"))
            except Exception:
                data = {}
            if "tenants_auth" not in data or not isinstance(data["tenants_auth"], dict):
                data = {"tenants_auth": data}
            data["tenants_auth"][sk] = private_record
            data["tenants_auth"][pk] = public_record
            sm.put_secret_value(SecretId=secret_name, SecretString=json.dumps(data))
        else:
            param_name = (
                os.environ.get("TENANTS_AUTH_SSM_PARAM")
                or os.environ.get("TENANTS_AUTH_PARAM")
                or storage_cfg.get("tenants_auth_ssm_param")
                or "/ai_pod/tenants_auth"
            )
            ssm = boto3.client("ssm", region_name=region)
            try:
                resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
                data = json.loads(resp["Parameter"]["Value"])
            except Exception:
                data = {}
            if "tenants_auth" not in data or not isinstance(data["tenants_auth"], dict):
                data = {"tenants_auth": data}
            data["tenants_auth"][sk] = private_record
            data["tenants_auth"][pk] = public_record
            ssm.put_parameter(
                Name=param_name,
                Value=json.dumps(data),
                Type="SecureString",
                Overwrite=True,
            )
    else:
        # Local YAML persistence
        local_path = resolve_path("config/tenants_auth.local.yaml")
        data = {}
        if local_path.exists():
            with open(local_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

        if "tenants_auth" not in data or not isinstance(data["tenants_auth"], dict):
            data["tenants_auth"] = {}

        data["tenants_auth"][sk] = private_record
        data["tenants_auth"][pk] = public_record

        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)

    # Immediately register in in-memory auth structures
    try:
        from src.api.auth import TENANT_AUTH_MAPPING, TENANT_KEY_RECORDS
        TENANT_KEY_RECORDS[sk] = private_record
        TENANT_KEY_RECORDS[pk] = public_record
        TENANT_AUTH_MAPPING[sk] = clean_tenant
        TENANT_AUTH_MAPPING[pk] = clean_tenant
    except ImportError:
        pass

    return {
        "status": "ok",
        "tenant_id": clean_tenant,
        "private_key": {
            "key": sk,
            "key_type": "private",
            "created_at": now_iso,
        },
        "public_key": {
            "key": pk,
            "key_type": "public",
            "created_at": now_iso,
        },
        "sk": sk,
        "pk": pk,
    }


def revoke_tenant_keys(
    tenant_id: str,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Revoke all active API keys belonging to a tenant.

    Deletes them from persistent storage (SSM / Secrets Manager or local file)
    and removes them immediately from in-memory authentication structures.

    Args:
        tenant_id: Tenant identifier.
        config: Optional loaded configuration dictionary.

    Returns:
        List of revoked key strings.
    """
    clean_tenant = tenant_id.strip()
    if not clean_tenant:
        raise ValueError("tenant_id cannot be blank")

    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    storage_cfg = config.get("storage", {})
    backend = os.environ.get(
        "STORAGE_BACKEND", storage_cfg.get("backend", "local")
    ).strip().lower()

    revoked_keys: list[str] = []

    if backend == "s3":
        import boto3

        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or storage_cfg.get("region")
            or "us-east-1"
        )
        secret_name = (
            os.environ.get("TENANTS_AUTH_SECRET_NAME")
            or storage_cfg.get("tenants_auth_secret_name")
        )

        if secret_name:
            sm = boto3.client("secretsmanager", region_name=region)
            try:
                resp = sm.get_secret_value(SecretId=secret_name)
                data = json.loads(resp.get("SecretString", "{}"))
            except Exception:
                data = {}
            mapping = data.get("tenants_auth", data)
            if isinstance(mapping, dict):
                to_delete = [
                    k for k, v in mapping.items()
                    if (isinstance(v, dict) and v.get("tenant_id") == clean_tenant)
                    or (isinstance(v, str) and v == clean_tenant)
                ]
                for k in to_delete:
                    del mapping[k]
                    revoked_keys.append(k)
                data["tenants_auth"] = mapping
                sm.put_secret_value(SecretId=secret_name, SecretString=json.dumps(data))
        else:
            param_name = (
                os.environ.get("TENANTS_AUTH_SSM_PARAM")
                or os.environ.get("TENANTS_AUTH_PARAM")
                or storage_cfg.get("tenants_auth_ssm_param")
                or "/ai_pod/tenants_auth"
            )
            ssm = boto3.client("ssm", region_name=region)
            try:
                resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
                data = json.loads(resp["Parameter"]["Value"])
            except Exception:
                data = {}
            mapping = data.get("tenants_auth", data)
            if isinstance(mapping, dict):
                to_delete = [
                    k for k, v in mapping.items()
                    if (isinstance(v, dict) and v.get("tenant_id") == clean_tenant)
                    or (isinstance(v, str) and v == clean_tenant)
                ]
                for k in to_delete:
                    del mapping[k]
                    revoked_keys.append(k)
                data["tenants_auth"] = mapping
                ssm.put_parameter(
                    Name=param_name,
                    Value=json.dumps(data),
                    Type="SecureString",
                    Overwrite=True,
                )
    else:
        # Local YAML
        local_path = resolve_path("config/tenants_auth.local.yaml")
        data = {}
        if local_path.exists():
            try:
                with open(local_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                data = {}

        mapping = data.get("tenants_auth", {})
        if isinstance(mapping, dict):
            to_delete = [
                k for k, v in mapping.items()
                if (isinstance(v, dict) and v.get("tenant_id") == clean_tenant)
                or (isinstance(v, str) and v == clean_tenant)
            ]
            for k in to_delete:
                del mapping[k]
                revoked_keys.append(k)
            data["tenants_auth"] = mapping
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False)

    # Immediately purge from in-memory lookup structures
    try:
        from src.api.auth import TENANT_AUTH_MAPPING, TENANT_KEY_RECORDS

        for k in list(revoked_keys):
            TENANT_KEY_RECORDS.pop(k, None)
            TENANT_AUTH_MAPPING.pop(k, None)

        mem_keys = [
            k for k, v in list(TENANT_AUTH_MAPPING.items()) if v == clean_tenant
        ]
        for k in mem_keys:
            TENANT_AUTH_MAPPING.pop(k, None)
            TENANT_KEY_RECORDS.pop(k, None)
            if k not in revoked_keys:
                revoked_keys.append(k)
    except ImportError:
        pass

    return revoked_keys


def get_tenant_public_key(
    tenant_id: str,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Retrieve the active public API key for a tenant."""
    clean_tenant = tenant_id.strip()
    from src.utils.config import get_tenant_auth_records

    records = get_tenant_auth_records(config)
    for k, rec in records.items():
        if rec.get("tenant_id") == clean_tenant and (
            rec.get("key_type") == "public" or k.startswith("pk-")
        ):
            return k

    # Check in-memory records
    try:
        from src.api.auth import TENANT_KEY_RECORDS

        for k, rec in TENANT_KEY_RECORDS.items():
            if rec.get("tenant_id") == clean_tenant and (
                rec.get("key_type") == "public" or k.startswith("pk-")
            ):
                return k
    except ImportError:
        pass

    return None


def regenerate_tenant_keys(
    tenant_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invalidate existing keys for tenant and issue a brand new key pair."""
    revoke_tenant_keys(tenant_id, config=config)
    return issue_tenant_keys(tenant_id, config=config)

