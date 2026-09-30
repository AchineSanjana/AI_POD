"""FastAPI endpoints for Shopify store connection (OAuth) and product catalog synchronization."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.api.auth import get_current_tenant
from src.catalog.feed_sync import sync_tenant_catalog
from src.integrations.shopify.client import (
    DEFAULT_SHOPIFY_SCOPES,
    build_authorization_url,
    exchange_code_for_token,
    normalize_shop_domain,
    verify_shopify_hmac,
)
from src.integrations.shopify.storage import (
    delete_shopify_connection,
    get_shopify_connection,
    save_shopify_connection,
)
from src.utils.config import load_config

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/integrations/shopify",
    tags=["integrations"],
)

# In-memory store for pending OAuth states: state -> {tenant_id, shop, created_at}
PENDING_OAUTH_STATES: dict[str, dict[str, Any]] = {}


def _get_shopify_oauth_config() -> tuple[str, str, str]:
    """Retrieve Shopify client_id, client_secret, and redirect_uri from env/config."""
    cfg = load_config()
    integrations_cfg = cfg.get("integrations", {}).get("shopify", {})

    client_id = (
        os.environ.get("SHOPIFY_CLIENT_ID")
        or os.environ.get("SHOPIFY_API_KEY")
        or integrations_cfg.get("client_id")
        or "mock_shopify_client_id"
    )
    client_secret = (
        os.environ.get("SHOPIFY_CLIENT_SECRET")
        or os.environ.get("SHOPIFY_API_SECRET")
        or integrations_cfg.get("client_secret")
        or "mock_shopify_client_secret"
    )
    redirect_uri = (
        os.environ.get("SHOPIFY_REDIRECT_URI")
        or integrations_cfg.get("redirect_uri")
        or "http://localhost:8000/v1/integrations/shopify/callback"
    )

    return client_id.strip(), client_secret.strip(), redirect_uri.strip()


@router.get(
    "/authorize",
    summary="Start Shopify OAuth Connect Store flow",
    description="Generates authorization URL and state nonce to redirect merchant to Shopify.",
)
def authorize_shopify(
    shop: str = Query(..., description="Merchant Shopify shop domain (e.g. 'my-store.myshopify.com')"),
    redirect: bool = Query(False, description="If True, returns HTTP 307 redirect to Shopify. If False, returns JSON."),
    current_tenant: str = Depends(get_current_tenant),
) -> Any:
    """Start Shopify OAuth flow for the authenticated tenant."""
    try:
        norm_shop = normalize_shop_domain(shop)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    client_id, _, default_redirect_uri = _get_shopify_oauth_config()

    # Generate a cryptographically secure state nonce
    state = secrets.token_urlsafe(24)
    PENDING_OAUTH_STATES[state] = {
        "tenant_id": current_tenant,
        "shop": norm_shop,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    auth_url = build_authorization_url(
        shop=norm_shop,
        state=state,
        client_id=client_id,
        redirect_uri=default_redirect_uri,
        scopes=DEFAULT_SHOPIFY_SCOPES,
    )

    if redirect:
        return RedirectResponse(url=auth_url, status_code=307)

    return {
        "status": "pending_authorization",
        "tenant_id": current_tenant,
        "shop": norm_shop,
        "state": state,
        "authorization_url": auth_url,
    }


@router.get(
    "/callback",
    summary="Shopify OAuth Callback",
    description="Receives authorization code, exchanges it for permanent token, and populates products table.",
)
def shopify_callback(
    shop: str = Query(..., description="Shop domain from Shopify callback"),
    code: str = Query(..., description="Temporary authorization code"),
    state: str = Query(..., description="State nonce to verify and resolve tenant"),
    hmac: str | None = Query(None, description="Shopify HMAC signature"),
    request: Request = None,
) -> Any:
    """Complete Shopify OAuth flow, save credentials securely, and sync product catalog."""
    # 1. Validate state nonce and resolve tenant
    state_record = PENDING_OAUTH_STATES.pop(state, None)
    if not state_record:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state nonce. Please restart the Connect Store flow.",
        )

    tenant_id = state_record["tenant_id"]
    try:
        norm_shop = normalize_shop_domain(shop)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    client_id, client_secret, _ = _get_shopify_oauth_config()

    # 2. Verify HMAC if provided and secret is configured
    if hmac and request is not None and client_secret and client_secret != "mock_shopify_client_secret":
        query_dict = dict(request.query_params)
        if not verify_shopify_hmac(query_dict, client_secret):
            raise HTTPException(status_code=401, detail="HMAC signature verification failed")

    # 3. Exchange code for access token
    try:
        token_data = exchange_code_for_token(
            shop=norm_shop,
            code=code,
            client_id=client_id,
            client_secret=client_secret,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Shopify token exchange failed: {exc}")

    access_token = token_data.get("access_token", "")
    scopes = token_data.get("scope", DEFAULT_SHOPIFY_SCOPES)

    # 4. Store connection securely per tenant (Step 15.2 pattern)
    save_shopify_connection(
        tenant_id=tenant_id,
        shop=norm_shop,
        access_token=access_token,
        scopes=scopes,
    )

    # 5. Immediately pull and sync product catalog
    try:
        sync_result = sync_tenant_catalog(tenant_id=tenant_id, mode="upsert")
    except Exception as exc:
        logger.warning("Initial catalog sync after Shopify connect failed for '%s': %s", tenant_id, exc)
        sync_result = {"status": "sync_failed", "error": str(exc)}

    return {
        "status": "connected",
        "tenant_id": tenant_id,
        "shop": norm_shop,
        "scopes": scopes,
        "catalog_sync": sync_result,
    }


@router.get(
    "/status",
    summary="Check Shopify Connection Status",
    description="Inspects whether the authenticated tenant is connected to Shopify.",
)
def shopify_connection_status(
    current_tenant: str = Depends(get_current_tenant),
) -> Any:
    """Return whether authenticated tenant has an active Shopify connection."""
    conn = get_shopify_connection(current_tenant)
    if not conn:
        return {
            "connected": False,
            "tenant_id": current_tenant,
            "message": "No Shopify store connected for this tenant.",
        }

    return {
        "connected": True,
        "tenant_id": current_tenant,
        "shop": conn.get("shop"),
        "scopes": conn.get("scopes"),
        "connected_at": conn.get("connected_at"),
    }


@router.post(
    "/sync",
    summary="Manually trigger Shopify catalog sync",
    description="Manually pulls product catalog from connected Shopify store and updates products table.",
)
def manual_shopify_sync(
    current_tenant: str = Depends(get_current_tenant),
) -> Any:
    """Trigger an immediate catalog sync for the authenticated tenant from Shopify."""
    conn = get_shopify_connection(current_tenant)
    if not conn:
        raise HTTPException(
            status_code=400,
            detail=f"Tenant '{current_tenant}' has no active Shopify connection.",
        )

    res = sync_tenant_catalog(tenant_id=current_tenant, mode="upsert")
    return res


@router.delete(
    "/disconnect",
    summary="Disconnect Shopify Store",
    description="Removes stored Shopify connection credentials for the authenticated tenant.",
)
def disconnect_shopify(
    current_tenant: str = Depends(get_current_tenant),
) -> Any:
    """Disconnect and purge stored Shopify credentials for the tenant."""
    deleted = delete_shopify_connection(current_tenant)
    return {
        "status": "disconnected" if deleted else "not_found",
        "tenant_id": current_tenant,
    }
