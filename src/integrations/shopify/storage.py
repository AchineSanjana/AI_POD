"""Secure token storage for Shopify platform connections.

Stores Shopify access tokens, shop domains, and connection metadata securely per-tenant,
following the exact same pattern established in Step 15.2 / Step 18.1:
- AWS Mode (backend == 's3'): Persists to AWS SSM Parameter Store or AWS Secrets Manager.
- Local Mode: Persists to config/shopify_connections.local.yaml (git-ignored local file).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from typing import Any

import yaml

from src.utils.config import load_config, resolve_path

logger = logging.getLogger(__name__)

LOCAL_CONNECTIONS_FILE = "config/shopify_connections.local.yaml"
DEFAULT_SSM_PARAM_PREFIX = "/ai_pod/shopify"


def _get_ssm_param_name(tenant_id: str, storage_cfg: dict[str, Any]) -> str:
    """Build SSM parameter name for a tenant's Shopify credentials."""
    prefix = (
        os.environ.get("SHOPIFY_CONNECTIONS_SSM_PARAM")
        or storage_cfg.get("shopify_connections_ssm_param")
        or DEFAULT_SSM_PARAM_PREFIX
    ).rstrip("/")
    return f"{prefix}/{tenant_id.strip()}"


def save_shopify_connection(
    tenant_id: str,
    shop: str,
    access_token: str,
    scopes: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Securely persist a tenant's Shopify access token and shop domain.

    Args:
        tenant_id: Tenant identifier.
        shop: Merchant shop domain.
        access_token: Permanent Shopify offline access token.
        scopes: Granted OAuth scopes.
        config: Optional loaded configuration dictionary.

    Returns:
        Dictionary representing the stored connection record.
    """
    clean_tenant = tenant_id.strip()
    if not clean_tenant:
        raise ValueError("tenant_id cannot be blank")

    cfg = config or load_config()
    storage_cfg = cfg.get("storage", {})
    backend = os.environ.get(
        "STORAGE_BACKEND", storage_cfg.get("backend", "local")
    ).strip().lower()

    record = {
        "tenant_id": clean_tenant,
        "shop": shop.strip(),
        "access_token": access_token.strip(),
        "scopes": scopes or "read_products",
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    if backend == "s3":
        import boto3

        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or storage_cfg.get("region")
            or "us-east-1"
        )
        secret_name = (
            os.environ.get("SHOPIFY_CONNECTIONS_SECRET_NAME")
            or storage_cfg.get("shopify_connections_secret_name")
        )

        if secret_name:
            sm = boto3.client("secretsmanager", region_name=region)
            try:
                resp = sm.get_secret_value(SecretId=secret_name)
                data = json.loads(resp.get("SecretString", "{}"))
            except Exception:
                data = {}
            if "shopify_connections" not in data or not isinstance(data["shopify_connections"], dict):
                data = {"shopify_connections": data}
            data["shopify_connections"][clean_tenant] = record
            sm.put_secret_value(SecretId=secret_name, SecretString=json.dumps(data))
        else:
            param_name = _get_ssm_param_name(clean_tenant, storage_cfg)
            ssm = boto3.client("ssm", region_name=region)
            ssm.put_parameter(
                Name=param_name,
                Value=json.dumps(record),
                Type="SecureString",
                Overwrite=True,
            )
        logger.info("Saved Shopify connection for tenant '%s' via AWS Parameter Store / Secrets Manager", clean_tenant)
    else:
        # Local mode: persist to config/shopify_connections.local.yaml
        local_path = resolve_path(LOCAL_CONNECTIONS_FILE)
        data: dict[str, Any] = {}
        if local_path.exists():
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                data = {}

        if "shopify_connections" not in data or not isinstance(data["shopify_connections"], dict):
            data = {"shopify_connections": {}}

        data["shopify_connections"][clean_tenant] = record
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        logger.info("Saved Shopify connection for tenant '%s' to '%s'", clean_tenant, local_path)

    return record


def get_shopify_connection(
    tenant_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Retrieve the stored Shopify connection for a tenant if one exists.

    Returns:
        Dict with keys: tenant_id, shop, access_token, scopes, connected_at; or None.
    """
    clean_tenant = tenant_id.strip()
    if not clean_tenant:
        return None

    cfg = config or load_config()
    storage_cfg = cfg.get("storage", {})
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
            os.environ.get("SHOPIFY_CONNECTIONS_SECRET_NAME")
            or storage_cfg.get("shopify_connections_secret_name")
        )

        if secret_name:
            sm = boto3.client("secretsmanager", region_name=region)
            try:
                resp = sm.get_secret_value(SecretId=secret_name)
                data = json.loads(resp.get("SecretString", "{}"))
                conns = data.get("shopify_connections", data)
                if isinstance(conns, dict):
                    return conns.get(clean_tenant)
            except Exception as exc:
                logger.debug("Failed loading secret '%s': %s", secret_name, exc)
                return None
        else:
            param_name = _get_ssm_param_name(clean_tenant, storage_cfg)
            ssm = boto3.client("ssm", region_name=region)
            try:
                resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
                val = resp["Parameter"]["Value"]
                return json.loads(val)
            except Exception as exc:
                logger.debug("No SSM parameter found for '%s': %s", param_name, exc)
                return None
    else:
        # Local mode: read from config/shopify_connections.local.yaml
        local_path = resolve_path(LOCAL_CONNECTIONS_FILE)
        if not local_path.exists():
            return None
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            conns = data.get("shopify_connections", data)
            if isinstance(conns, dict):
                return conns.get(clean_tenant)
        except Exception as exc:
            logger.debug("Failed loading local shopify connections file: %s", exc)
            return None

    return None


def list_shopify_connections(
    config: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """List all configured Shopify connections across all tenants."""
    cfg = config or load_config()
    storage_cfg = cfg.get("storage", {})
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
            os.environ.get("SHOPIFY_CONNECTIONS_SECRET_NAME")
            or storage_cfg.get("shopify_connections_secret_name")
        )
        if secret_name:
            sm = boto3.client("secretsmanager", region_name=region)
            try:
                resp = sm.get_secret_value(SecretId=secret_name)
                data = json.loads(resp.get("SecretString", "{}"))
                return data.get("shopify_connections", data)
            except Exception:
                return {}
        else:
            # Query by parameter path hierarchy
            ssm = boto3.client("ssm", region_name=region)
            prefix = (
                os.environ.get("SHOPIFY_CONNECTIONS_SSM_PARAM")
                or storage_cfg.get("shopify_connections_ssm_param")
                or DEFAULT_SSM_PARAM_PREFIX
            ).rstrip("/")
            try:
                resp = ssm.get_parameters_by_path(Path=prefix, WithDecryption=True)
                conns = {}
                for param in resp.get("Parameters", []):
                    try:
                        record = json.loads(param["Value"])
                        t_id = record.get("tenant_id")
                        if t_id:
                            conns[t_id] = record
                    except Exception:
                        pass
                return conns
            except Exception:
                return {}
    else:
        local_path = resolve_path(LOCAL_CONNECTIONS_FILE)
        if not local_path.exists():
            return {}
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            conns = data.get("shopify_connections", data)
            return conns if isinstance(conns, dict) else {}
        except Exception:
            return {}


def delete_shopify_connection(
    tenant_id: str,
    config: dict[str, Any] | None = None,
) -> bool:
    """Disconnect and remove a tenant's stored Shopify credentials."""
    clean_tenant = tenant_id.strip()
    cfg = config or load_config()
    storage_cfg = cfg.get("storage", {})
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
        param_name = _get_ssm_param_name(clean_tenant, storage_cfg)
        ssm = boto3.client("ssm", region_name=region)
        try:
            ssm.delete_parameter(Name=param_name)
            return True
        except Exception:
            return False
    else:
        local_path = resolve_path(LOCAL_CONNECTIONS_FILE)
        if not local_path.exists():
            return False
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            conns = data.get("shopify_connections", {})
            if clean_tenant in conns:
                del conns[clean_tenant]
                with open(local_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f)
                return True
        except Exception:
            return False
    return False
