"""Shopify OAuth and Admin API client for product catalog synchronization.

Provides helpers for:
- Normalizing and validating shop domains.
- Building OAuth authorization URLs and verifying HMAC signatures.
- Exchanging authorization codes for permanent access tokens.
- Fetching product catalogs from Shopify Admin API.
- Parsing Shopify products into canonical (product_id, product_name, price, category) records.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from typing import Any
import urllib.parse
import urllib.request

from src.catalog.feed_parser import _clean_price

logger = logging.getLogger(__name__)

DEFAULT_SHOPIFY_API_VERSION = "2024-01"
DEFAULT_SHOPIFY_SCOPES = "read_products"


def normalize_shop_domain(shop: str) -> str:
    """Normalize a merchant shop domain into a standard 'myshopify.com' hostname.

    Examples:
        - 'my-cool-store' -> 'my-cool-store.myshopify.com'
        - 'https://my-cool-store.myshopify.com/' -> 'my-cool-store.myshopify.com'
        - 'my-cool-store.myshopify.com' -> 'my-cool-store.myshopify.com'

    Raises:
        ValueError: If the shop domain is empty or contains invalid characters.
    """
    cleaned = shop.strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.split("/")[0].split(":")[0]

    if not cleaned:
        raise ValueError("Shop domain cannot be empty")

    if not cleaned.endswith(".myshopify.com"):
        cleaned = f"{cleaned}.myshopify.com"

    # Validate shop hostname format (subdomain.myshopify.com)
    subdomain = cleaned.split(".myshopify.com")[0]
    if not re.match(r"^[a-zA-Z0-9][-a-zA-Z0-9]*$", subdomain):
        raise ValueError(
            f"Invalid Shopify shop domain '{shop}': subdomain must be alphanumeric with hyphens"
        )

    return cleaned


def build_authorization_url(
    shop: str,
    state: str,
    client_id: str,
    redirect_uri: str,
    scopes: str = DEFAULT_SHOPIFY_SCOPES,
) -> str:
    """Construct Shopify OAuth 2.0 authorization URL for merchant redirection.

    Args:
        shop: Merchant shop name or domain.
        state: Unique cryptographic nonce for CSRF protection.
        client_id: Shopify app API key / client ID.
        redirect_uri: Registered app callback URL.
        scopes: Comma-separated list of OAuth scopes.

    Returns:
        Full Shopify OAuth URL string.
    """
    domain = normalize_shop_domain(shop)
    params = {
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    encoded = urllib.parse.urlencode(params)
    return f"https://{domain}/admin/oauth/authorize?{encoded}"


def verify_shopify_hmac(query_params: dict[str, Any], client_secret: str) -> bool:
    """Verify that a callback request originated from Shopify using HMAC-SHA256.

    Args:
        query_params: Dictionary of query parameters received in callback.
        client_secret: Shopify app API secret key.

    Returns:
        True if signature matches; False otherwise.
    """
    if not client_secret or not query_params:
        return False

    received_hmac = str(query_params.get("hmac", "")).strip().lower()
    if not received_hmac:
        return False

    # Extract all parameters except 'hmac' and 'signature'
    filtered_pairs = [
        (str(k), str(v))
        for k, v in query_params.items()
        if k not in ("hmac", "signature")
    ]
    # Sort lexicographically by key
    filtered_pairs.sort(key=lambda pair: pair[0])

    # Message string is formatted as key=value joined by '&'
    message = "&".join(f"{k}={v}" for k, v in filtered_pairs)

    digest = hmac.new(
        client_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(digest.lower(), received_hmac)


def exchange_code_for_token(
    shop: str,
    code: str,
    client_id: str,
    client_secret: str,
    timeout: int = 15,
) -> dict[str, Any]:
    """Exchange a temporary authorization code for a permanent Shopify access token.

    Args:
        shop: Merchant shop domain.
        code: Temporary authorization code from callback.
        client_id: Shopify app client ID.
        client_secret: Shopify app client secret.
        timeout: HTTP request timeout in seconds.

    Returns:
        Dict containing 'access_token' and 'scope'.

    Raises:
        RuntimeError: If token exchange fails or returns an error.
    """
    domain = normalize_shop_domain(shop)
    token_url = f"https://{domain}/admin/oauth/access_token"

    payload = json.dumps(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        token_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AI_POD-ShopifySync/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            if "access_token" not in data:
                raise RuntimeError(f"Shopify token response missing 'access_token': {data}")
            return data
    except Exception as exc:
        logger.error("Failed to exchange Shopify OAuth code for shop '%s': %s", domain, exc)
        raise RuntimeError(f"Failed to obtain Shopify access token for '{domain}': {exc}") from exc


def fetch_shopify_products(
    shop: str,
    access_token: str,
    limit: int = 250,
    api_version: str = DEFAULT_SHOPIFY_API_VERSION,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Fetch product records from Shopify Admin REST API.

    Handles pagination to retrieve the full catalog.

    Args:
        shop: Merchant shop domain.
        access_token: Permanent Shopify offline access token.
        limit: Number of products per page (max 250).
        api_version: Shopify API version (default 2024-01).
        timeout: HTTP request timeout in seconds.

    Returns:
        List of raw Shopify product objects.
    """
    domain = normalize_shop_domain(shop)
    base_url = f"https://{domain}/admin/api/{api_version}/products.json"

    headers = {
        "X-Shopify-Access-Token": access_token.strip(),
        "Accept": "application/json",
        "User-Agent": "AI_POD-ShopifySync/1.0",
    }

    all_products: list[dict[str, Any]] = []
    next_url: str | None = f"{base_url}?limit={min(limit, 250)}"

    while next_url:
        req = urllib.request.Request(next_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                products = data.get("products", [])
                all_products.extend(products)

                # Inspect 'Link' header for pagination rel="next"
                link_header = resp.headers.get("Link", "")
                next_url = _extract_next_page_url(link_header)
        except Exception as exc:
            logger.error("Failed fetching Shopify products from '%s': %s", next_url, exc)
            raise RuntimeError(f"Failed to fetch products from Shopify for '{domain}': {exc}") from exc

    return all_products


def _extract_next_page_url(link_header: str) -> str | None:
    """Extract next page URL from HTTP Link header."""
    if not link_header:
        return None
    links = link_header.split(",")
    for link in links:
        parts = link.split(";")
        if len(parts) == 2 and 'rel="next"' in parts[1].lower():
            return parts[0].strip().strip("<>")
    return None


def parse_shopify_products(raw_products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse raw Shopify product records into canonical catalog rows.

    Canonical Schema:
        - product_id: str (Shopify product ID)
        - product_name: str (Product title)
        - price: float | None (Price from first variant or root)
        - category: str | None (product_type)

    Args:
        raw_products: List of raw Shopify product dictionaries.

    Returns:
        List of standardized product dicts conforming to ProductSchema.
    """
    rows: list[dict[str, Any]] = []

    for item in raw_products:
        if not isinstance(item, dict):
            continue

        prod_id = item.get("id")
        if not prod_id:
            continue

        title = item.get("title") or str(prod_id)
        category = item.get("product_type") or item.get("category") or None

        # Resolve price from variants
        price_val: Any = None
        variants = item.get("variants")
        if isinstance(variants, list) and variants:
            first_variant = variants[0]
            if isinstance(first_variant, dict):
                price_val = first_variant.get("price")
        if price_val is None:
            price_val = item.get("price")

        rows.append(
            {
                "product_id": str(prod_id).strip(),
                "product_name": str(title).strip(),
                "price": _clean_price(price_val),
                "category": str(category).strip() if category else None,
            }
        )

    return rows
