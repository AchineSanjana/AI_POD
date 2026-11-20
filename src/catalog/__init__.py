"""Catalog feed ingestion, synchronization, and tenant catalogue management module."""

from src.catalog.active_set import clear_active_catalog_cache, get_active_catalog
from src.catalog.audit import get_catalog_history, record_catalog_audit
from src.catalog.feed_parser import fetch_catalog_feed, parse_catalog_feed
from src.catalog.feed_sync import (
    sync_all_tenant_catalogs,
    sync_tenant_catalog,
    upsert_tenant_products,
)
from src.catalog.service import (
    CatalogError,
    ConcurrentModificationError,
    DuplicateProductError,
    InvalidOperationError,
    ProductNotFoundError,
    SnapshotError,
    add_product,
    bulk_action,
    commit_upload,
    delete_product,
    ensure_catalog_exists,
    generate_catalog_template,
    get_catalog_summary,
    list_products,
    load_catalog,
    parse_and_preview_upload,
    restore_product,
    save_catalog,
    undo_last_commit,
    update_product,
)

__all__ = [
    "CatalogError",
    "clear_active_catalog_cache",
    "get_active_catalog",
    "ConcurrentModificationError",
    "DuplicateProductError",
    "InvalidOperationError",
    "ProductNotFoundError",
    "SnapshotError",
    "add_product",
    "bulk_action",
    "commit_upload",
    "delete_product",
    "ensure_catalog_exists",
    "fetch_catalog_feed",
    "generate_catalog_template",
    "get_catalog_history",
    "get_catalog_summary",
    "list_products",
    "load_catalog",
    "parse_and_preview_upload",
    "parse_catalog_feed",
    "record_catalog_audit",
    "restore_product",
    "save_catalog",
    "sync_all_tenant_catalogs",
    "sync_tenant_catalog",
    "undo_last_commit",
    "update_product",
    "upsert_tenant_products",
]
