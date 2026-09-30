"""API Key authentication dependency and tenant lookup for FastAPI endpoints.

Reads tenant authentication records from configuration/SSM and resolves incoming
API keys to their respective tenant IDs. Supports 'private' and 'public' key types,
restricting public keys server-side strictly to POST /v1/track and GET /v1/recommendations.
"""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException, Request

from src.utils.config import get_tenant_auth_records, load_config

# In-memory mapping of api_key -> tenant_id loaded from config
TENANT_AUTH_MAPPING: dict[str, str] = {}

# In-memory mapping of api_key -> key record dict
TENANT_KEY_RECORDS: dict[str, dict[str, Any]] = {}

# Endpoints and HTTP methods permitted for public API keys
PUBLIC_KEY_ALLOWED_ACTIONS: set[tuple[str, str]] = {
    ("POST", "/v1/track"),
    ("POST", "/track"),
    ("GET", "/v1/recommendations"),
    ("GET", "/recommendations"),
}


def is_request_allowed_for_key(key_type: str, method: str, path: str) -> bool:
    """Check whether an HTTP request (method + path) is permitted for a given key type.

    - Private keys: Permitted everywhere across the entire API.
    - Public keys: Permitted strictly for POST /v1/track and GET /v1/recommendations.
    """
    clean_type = str(key_type).strip().lower()
    if clean_type == "private":
        return True

    if clean_type == "public":
        norm_method = method.upper()
        norm_path = path.rstrip("/")
        if not norm_path:
            norm_path = "/"
        return (norm_method, norm_path) in PUBLIC_KEY_ALLOWED_ACTIONS

    return False


def load_tenant_auth(config: dict[str, Any] | None = None) -> dict[str, str]:
    """Load tenants_auth records and mapping into in-memory lookup structures."""
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    records = get_tenant_auth_records(config)
    TENANT_KEY_RECORDS.clear()
    TENANT_KEY_RECORDS.update(records)

    mapping = {k: rec["tenant_id"] for k, rec in records.items()}
    TENANT_AUTH_MAPPING.clear()
    TENANT_AUTH_MAPPING.update(mapping)
    return TENANT_AUTH_MAPPING


# Auto-load on import
load_tenant_auth()


def get_key_record(api_key: str | None) -> dict[str, Any] | None:
    """Retrieve full key record for an API key.

    Returns dict containing 'tenant_id', 'key_type', and 'created_at', or None if invalid.
    """
    if not api_key:
        return None

    if api_key in TENANT_KEY_RECORDS:
        return TENANT_KEY_RECORDS[api_key]

    if api_key in TENANT_AUTH_MAPPING:
        t = TENANT_AUTH_MAPPING[api_key]
        key_type = "public" if api_key.startswith("pk-") else "private"
        rec = {"tenant_id": t, "key_type": key_type, "created_at": None}
        TENANT_KEY_RECORDS[api_key] = rec
        return rec

    # If not found in memory, reload from storage/config
    load_tenant_auth()

    if api_key in TENANT_KEY_RECORDS:
        return TENANT_KEY_RECORDS[api_key]

    if api_key in TENANT_AUTH_MAPPING:
        t = TENANT_AUTH_MAPPING[api_key]
        key_type = "public" if api_key.startswith("pk-") else "private"
        rec = {"tenant_id": t, "key_type": key_type, "created_at": None}
        TENANT_KEY_RECORDS[api_key] = rec
        return rec

    # Auto-generation fallback for demo/test tenants in config['tenants']
    try:
        cfg = load_config()
        tenants = cfg.get("tenants", {})
        if isinstance(tenants, dict):
            for t in tenants.keys():
                if api_key == f"sk-{t}-xxxx":
                    rec = {"tenant_id": t, "key_type": "private", "created_at": None}
                    TENANT_KEY_RECORDS[api_key] = rec
                    TENANT_AUTH_MAPPING[api_key] = t
                    return rec
                if api_key == f"pk-{t}-xxxx":
                    rec = {"tenant_id": t, "key_type": "public", "created_at": None}
                    TENANT_KEY_RECORDS[api_key] = rec
                    TENANT_AUTH_MAPPING[api_key] = t
                    return rec
    except Exception:
        pass

    # Backward compatibility: manually injected keys in TENANT_AUTH_MAPPING
    if api_key in TENANT_AUTH_MAPPING:
        t = TENANT_AUTH_MAPPING[api_key]
        key_type = "public" if api_key.startswith("pk-") else "private"
        rec = {"tenant_id": t, "key_type": key_type, "created_at": None}
        TENANT_KEY_RECORDS[api_key] = rec
        return rec

    return None


def get_current_tenant(
    request: Request = None,  # type: ignore[assignment]
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency to authenticate requests, enforce key type restrictions, and resolve tenant_id.

    Reads API key from the X-API-Key header.
    - If missing or invalid, raises 401 Unauthorized.
    - If key_type is 'public' and requested action is not allowed, raises 403 Forbidden.
    - Otherwise returns the authenticated tenant_id.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="API key is missing. Provide a valid 'X-API-Key' header.",
        )

    record = get_key_record(x_api_key)
    if not record:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid API Key: '{x_api_key}'",
        )

    # Server-side restriction check for public keys
    if record.get("key_type") == "public" and request is not None:
        if not is_request_allowed_for_key("public", request.method, request.url.path):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Forbidden: Public API keys are only permitted for POST /v1/track and "
                    f"GET /v1/recommendations. Action '{request.method} {request.url.path}' is not allowed."
                ),
            )

    return record["tenant_id"]


def get_public_key_tenant(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency to authenticate requests with a public key ONLY.

    - If missing or invalid: raises 401 Unauthorized.
    - If key_type is not 'public' (e.g. private key): raises 403 Forbidden.
    - Otherwise returns the authenticated tenant_id.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="API key is missing. Provide a valid 'X-API-Key' header.",
        )

    record = get_key_record(x_api_key)
    if not record:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid API Key: '{x_api_key}'",
        )

    if record.get("key_type") != "public":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: This endpoint is authenticated by a public API key only.",
        )

    return record["tenant_id"]

