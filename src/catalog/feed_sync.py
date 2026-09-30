"""Catalog synchronization service for tenant products in S3/storage.

Supports:
1. Direct platform connections (e.g. Shopify Admin API OAuth) - takes PRIORITY.
2. External product feed URLs (e.g. Google Shopping XML / JSON feeds).

Syncs product records into (product_id, product_name, price, category) and
replaces or upserts into data/processed/{tenant_id}/products.csv.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd

from src.catalog.feed_parser import fetch_catalog_feed, parse_catalog_feed
from src.core.schema import ProductSchema
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import get_tenant_config, load_config

logger = logging.getLogger(__name__)


def upsert_tenant_products(
    tenant_id: str,
    feed_rows: list[dict[str, Any]],
    storage: StorageBackend,
    mode: str = "upsert",
) -> dict[str, int]:
    """Upsert or replace tenant products in S3 with fetched catalog feed rows.

    Args:
        tenant_id: Tenant identifier.
        feed_rows: List of product records (product_id, product_name, price, category).
        storage: StorageBackend instance (e.g. S3Storage or LocalStorage).
        mode: 'upsert' (merge with existing catalog, updating matches and keeping unmentioned)
              or 'replace' (completely overwrite with feed products).

    Returns:
        Dict with summary counts: {'fetched': int, 'added': int, 'updated': int, 'total': int}
    """
    if not feed_rows:
        logger.warning("No products in feed to sync for tenant '%s'", tenant_id)
        return {"fetched": 0, "added": 0, "updated": 0, "total": 0}

    path = f"data/processed/{tenant_id}/products.csv"
    feed_df = pd.DataFrame(feed_rows)
    feed_df["product_id"] = feed_df["product_id"].astype(str).str.strip()

    existing_df = pd.DataFrame()
    if storage.exists(path):
        try:
            content = storage.read_file(path)
            if content and content.strip():
                existing_df = pd.read_csv(io.BytesIO(content))
                if "product_id" in existing_df.columns:
                    existing_df["product_id"] = (
                        existing_df["product_id"].astype(str).str.strip()
                    )
        except Exception as exc:
            logger.warning(
                "Could not load existing products.csv for tenant '%s', starting fresh: %s",
                tenant_id,
                exc,
            )

    feed_ids = set(feed_df["product_id"])

    if mode == "replace" or existing_df.empty or "product_id" not in existing_df.columns:
        combined_df = feed_df.copy()
        added = len(feed_df)
        updated = 0
    else:
        existing_ids = set(existing_df["product_id"])
        updated = len(feed_ids.intersection(existing_ids))
        added = len(feed_ids - existing_ids)

        # 1. Keep existing rows that are not present in feed
        untouched = existing_df[~existing_df["product_id"].isin(feed_ids)].copy()

        # 2. For matching rows, combine columns (feed updates product_name, price, category)
        combined_df = pd.concat([untouched, feed_df], ignore_index=True)

    # 3. Deduplicate strictly by product_id (keeping last updated row)
    combined_df = combined_df.drop_duplicates(subset=["product_id"], keep="last").reset_index(drop=True)

    # 4. Standardize column order (product_id first, then product_name, then others)
    cols = list(combined_df.columns)
    ordered = ["product_id"]
    if "product_name" in cols:
        ordered.append("product_name")
    ordered.extend([c for c in cols if c not in ("product_id", "product_name")])
    combined_df = combined_df[ordered]

    # 5. Validate schema
    schema = ProductSchema()
    schema.validate(combined_df)

    # 6. Save back to S3 / storage
    csv_bytes = combined_df.to_csv(index=False).encode("utf-8")
    storage.write_file(path, csv_bytes)

    logger.info(
        "Successfully synced catalog for tenant '%s': fetched=%d, added=%d, updated=%d, total=%d",
        tenant_id,
        len(feed_rows),
        added,
        updated,
        len(combined_df),
    )

    return {
        "fetched": len(feed_rows),
        "added": added,
        "updated": updated,
        "total": len(combined_df),
    }


def sync_tenant_catalog(
    tenant_id: str,
    feed_url: str | None = None,
    storage: StorageBackend | None = None,
    mode: str = "upsert",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch and sync product catalog for a specific tenant.

    Priority Order:
    1. Direct Platform Connection (e.g. Shopify Admin API with stored access token)
    2. Feed URL (Google Shopping XML/JSON feed)

    Args:
        tenant_id: Target tenant identifier.
        feed_url: Optional explicit catalog feed URL.
        storage: Optional StorageBackend instance.
        mode: 'upsert' or 'replace'.
        config: Optional loaded configuration dict.

    Returns:
        Summary dict containing status, sync source ('shopify' or 'feed'), and metrics.
    """
    cfg = config or load_config()
    storage_backend = storage or get_storage_backend(cfg)

    # 1. Platform connection check (Shopify) - Takes PRIORITY over feed URL
    from src.integrations.shopify.client import (
        fetch_shopify_products,
        parse_shopify_products,
    )
    from src.integrations.shopify.storage import get_shopify_connection

    shopify_conn = get_shopify_connection(tenant_id, config=cfg)
    if shopify_conn and shopify_conn.get("access_token") and shopify_conn.get("shop"):
        shop = shopify_conn["shop"]
        access_token = shopify_conn["access_token"]
        logger.info(
            "Syncing catalog for tenant '%s' via Shopify platform connection (%s)...",
            tenant_id,
            shop,
        )
        raw_products = fetch_shopify_products(shop=shop, access_token=access_token)
        product_rows = parse_shopify_products(raw_products)
        metrics = upsert_tenant_products(
            tenant_id=tenant_id,
            feed_rows=product_rows,
            storage=storage_backend,
            mode=mode,
        )
        return {
            "status": "success",
            "tenant_id": tenant_id,
            "source": "shopify",
            "shop": shop,
            **metrics,
        }

    # 2. Feed URL fallback
    url = feed_url
    if not url:
        tenant_block = cfg.get("tenants", {}).get(tenant_id, {})
        if isinstance(tenant_block, dict) and tenant_block.get("catalog_feed_url"):
            url = str(tenant_block["catalog_feed_url"]).strip()
        else:
            try:
                tenant_cfg = get_tenant_config(cfg, tenant_id)
                url = tenant_cfg.catalog_feed_url
            except Exception:
                url = None

    if not url:
        logger.debug("No platform connection or catalog_feed_url for tenant '%s', skipping sync.", tenant_id)
        return {"status": "skipped", "tenant_id": tenant_id, "reason": "no_source_configured"}

    logger.info("Fetching catalog feed for tenant '%s' from: %s", tenant_id, url)
    content, content_type = fetch_catalog_feed(url)

    logger.info("Parsing catalog feed for tenant '%s'...", tenant_id)
    feed_rows = parse_catalog_feed(content, content_type=content_type)

    logger.info(
        "Parsed %d product(s) from feed for tenant '%s'. Upserting into S3...",
        len(feed_rows),
        tenant_id,
    )
    metrics = upsert_tenant_products(
        tenant_id=tenant_id,
        feed_rows=feed_rows,
        storage=storage_backend,
        mode=mode,
    )

    return {
        "status": "success",
        "tenant_id": tenant_id,
        "source": "feed",
        "feed_url": url,
        **metrics,
    }


def sync_all_tenant_catalogs(
    config: dict[str, Any] | None = None,
    storage: StorageBackend | None = None,
    mode: str = "upsert",
) -> list[dict[str, Any]]:
    """Scan all tenants and synchronize product catalogs using platform connections or feed URLs.

    If a tenant has both a platform connection and a feed URL, the platform connection takes priority.

    Args:
        config: Optional loaded configuration dictionary.
        storage: Optional StorageBackend instance.
        mode: 'upsert' or 'replace'.

    Returns:
        List of result summaries per tenant.
    """
    cfg = config or load_config()
    storage_backend = storage or get_storage_backend(cfg)

    # Collect all tenant IDs from config and active Shopify connections
    tenant_ids: set[str] = set()
    tenants = cfg.get("tenants", {})
    if isinstance(tenants, dict):
        tenant_ids.update(tenants.keys())

    from src.integrations.shopify.storage import list_shopify_connections

    shopify_conns = list_shopify_connections(cfg)
    tenant_ids.update(shopify_conns.keys())

    results: list[dict[str, Any]] = []

    for t_id in sorted(tenant_ids):
        try:
            res = sync_tenant_catalog(
                tenant_id=t_id,
                storage=storage_backend,
                mode=mode,
                config=cfg,
            )
            if res.get("status") != "skipped":
                results.append(res)
        except Exception as exc:
            logger.exception("Failed to sync catalog for tenant '%s': %s", t_id, exc)
            results.append(
                {
                    "status": "error",
                    "tenant_id": t_id,
                    "error": str(exc),
                }
            )

    return results
