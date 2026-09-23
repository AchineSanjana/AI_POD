"""API Key authentication dependency and tenant lookup for FastAPI endpoints.

Reads the tenants_auth mapping from config.yaml and resolves incoming API keys
to their respective tenant IDs.
"""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException

from src.utils.config import get_tenant_auth_mapping, load_config

# In-memory mapping of api_key -> tenant_id loaded from config
TENANT_AUTH_MAPPING: dict[str, str] = {}


def load_tenant_auth(config: dict[str, Any] | None = None) -> dict[str, str]:
    """Load tenants_auth mapping into in-memory lookup structure."""
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    mapping = get_tenant_auth_mapping(config)
    TENANT_AUTH_MAPPING.clear()
    TENANT_AUTH_MAPPING.update(mapping)
    return TENANT_AUTH_MAPPING


# Auto-load on import
load_tenant_auth()


def get_current_tenant(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency to authenticate requests and resolve tenant_id.

    Reads API key from the X-API-Key header and matches it against the configured
    tenants_auth mapping. If missing or invalid, raises 401 Unauthorized.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="API key is missing. Provide a valid 'X-API-Key' header.",
        )

    if not TENANT_AUTH_MAPPING:
        load_tenant_auth()

    if x_api_key not in TENANT_AUTH_MAPPING:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid API Key: '{x_api_key}'",
        )

    return TENANT_AUTH_MAPPING[x_api_key]
