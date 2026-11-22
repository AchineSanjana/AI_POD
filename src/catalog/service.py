"""Core service and business logic for tenant-managed product catalogue.

Features:
- Source of Truth: data/catalog/{tenant_id}/catalog.csv with atomic writes.
- Seeding: Auto-seeds from data/processed/{tenant}/products.csv on first access.
- Optimistic Concurrency: Tracks file version markers and prevents concurrent overwrite collisions (HTTP 409).
- Soft Delete & Permanent Delete lifecycle: Soft delete sets status=archived; permanent delete only allowed on archived items.
- Batch Upload Pipeline: Preview with validation (<=100k rows, required fields, duplicate IDs, row numbers), and commit with snapshotting.
- Snapshots & Undo: Keeps last 10 snapshots and restores pre-commit states.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import logging
import math
import os
import re
import secrets
import time
from typing import Any
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd

from src.catalog.audit import get_catalog_history, record_catalog_audit
from src.catalog.feed_parser import _clean_price, parse_catalog_feed
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend

logger = logging.getLogger(__name__)

STANDARD_COLUMNS = [
    "product_id",
    "product_name",
    "category",
    "status",
    "brand",
    "price",
    "in_stock",
    "description",
    "image_url",
    "product_url",
    "created_at",
    "updated_at",
]

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_UPLOAD_ROWS = 100_000
PENDING_EXPIRATION_SECONDS = 3600  # 1 hour
MAX_SNAPSHOTS = 10


class CatalogError(Exception):
    """Base exception for catalog service errors."""
    pass


class ConcurrentModificationError(CatalogError):
    """Raised when an optimistic concurrency version marker check fails."""
    pass


class DuplicateProductError(CatalogError):
    """Raised when attempting to add a product whose product_id already exists."""
    pass


class ProductNotFoundError(CatalogError):
    """Raised when a product is not found in the catalogue."""
    pass


class InvalidOperationError(CatalogError):
    """Raised when an invalid operation is performed (e.g. permanent delete on active item)."""
    pass


class SnapshotError(CatalogError):
    """Raised when a snapshot operation fails or no snapshot is available."""
    pass


def get_catalog_path(tenant_id: str) -> str:
    """Return canonical logical storage path for a tenant's catalog."""
    return f"data/catalog/{tenant_id}/catalog.csv"


def get_processed_path(tenant_id: str) -> str:
    """Return logical storage path for a tenant's processed products."""
    return f"data/processed/{tenant_id}/products.csv"


def get_snapshots_prefix(tenant_id: str) -> str:
    """Return prefix for tenant catalog snapshots."""
    return f"data/catalog/{tenant_id}/snapshots/"


def get_pending_path(tenant_id: str, upload_id: str) -> str:
    """Return storage path for a pending upload."""
    return f"data/catalog/{tenant_id}/pending/{upload_id}.json"


def _clean_str(val: Any) -> str | None:
    """Clean and strip string, returning None for empty or NaN values."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None


def _format_product_row(row_dict: dict[str, Any]) -> dict[str, Any]:
    """Format row dictionary into clean JSON-serializable product representation."""
    cleaned: dict[str, Any] = {}
    for k, v in row_dict.items():
        if pd.isna(v) or v is None:
            cleaned[k] = None
        elif k == "in_stock":
            try:
                cleaned[k] = int(v)
            except (ValueError, TypeError):
                cleaned[k] = 1
        elif k == "price":
            try:
                cleaned[k] = float(v)
            except (ValueError, TypeError):
                cleaned[k] = None
        else:
            cleaned[k] = str(v).strip()
    return cleaned


def ensure_catalog_exists(
    tenant_id: str,
    storage: StorageBackend | None = None,
    who: str = "system",
) -> tuple[pd.DataFrame, str | None]:
    """Ensure catalog.csv exists for tenant, seeding from products.csv if necessary.

    Returns:
        tuple[DataFrame, version_marker]
    """
    if storage is None:
        storage = get_storage_backend()

    cat_path = get_catalog_path(tenant_id)
    if storage.exists(cat_path):
        return load_catalog(tenant_id, storage=storage, auto_seed=False)

    # Need seeding: check data/processed/{tenant_id}/products.csv
    proc_path = get_processed_path(tenant_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    if storage.exists(proc_path):
        logger.info("Seeding catalog.csv for tenant '%s' from '%s'", tenant_id, proc_path)
        try:
            content = storage.read_file(proc_path)
            proc_df = pd.read_csv(io.BytesIO(content))
        except Exception as exc:
            logger.warning("Failed to read '%s' for seeding '%s': %s", proc_path, tenant_id, exc)
            proc_df = pd.DataFrame()
    else:
        proc_df = pd.DataFrame()

    if not proc_df.empty:
        # Standardize columns
        proc_df.columns = [str(c).strip() for c in proc_df.columns]
        if "product_id" not in proc_df.columns:
            # Fallback if first column might be ID
            proc_df.rename(columns={proc_df.columns[0]: "product_id"}, inplace=True)

        proc_df["product_id"] = proc_df["product_id"].astype(str).str.strip()
        # Drop rows with empty product_id
        proc_df = proc_df[proc_df["product_id"] != ""].copy()
        proc_df = proc_df.drop_duplicates(subset=["product_id"], keep="first")

        if "product_name" not in proc_df.columns:
            proc_df["product_name"] = None
        for col in ("title", "name"):
            if col in proc_df.columns:
                proc_df["product_name"] = proc_df["product_name"].fillna(proc_df[col])
        proc_df["product_name"] = proc_df["product_name"].fillna(proc_df["product_id"]).astype(str).str.strip()

        if "category" not in proc_df.columns:
            proc_df["category"] = None
        for col in ("product_type", "google_product_category"):
            if col in proc_df.columns:
                proc_df["category"] = proc_df["category"].fillna(proc_df[col])
        proc_df["category"] = proc_df["category"].fillna("General").astype(str).str.strip()
        proc_df.loc[proc_df["category"] == "", "category"] = "General"

        proc_df["status"] = "active"

        if "in_stock" not in proc_df.columns:
            proc_df["in_stock"] = 1
        else:
            proc_df["in_stock"] = pd.to_numeric(proc_df["in_stock"], errors="coerce").fillna(1).astype(int)

        if "created_at" not in proc_df.columns:
            proc_df["created_at"] = now_iso
        if "updated_at" not in proc_df.columns:
            proc_df["updated_at"] = now_iso

        # Ensure all standard columns exist
        for col in STANDARD_COLUMNS:
            if col not in proc_df.columns:
                proc_df[col] = None

        # Order standard columns first, followed by extra feature columns
        ordered_cols = [c for c in STANDARD_COLUMNS if c in proc_df.columns]
        extra_cols = [c for c in proc_df.columns if c not in STANDARD_COLUMNS]
        df = proc_df[ordered_cols + extra_cols].copy()
    else:
        # Initialize empty catalogue with standard schema
        df = pd.DataFrame(columns=STANDARD_COLUMNS)

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    storage.write_file(cat_path, csv_bytes)

    # Record audit log for seeding
    pids = df["product_id"].astype(str).tolist() if not df.empty else []
    record_catalog_audit(
        tenant_id=tenant_id,
        who=who,
        action="seed",
        product_ids=pids,
        details={"source": proc_path if storage.exists(proc_path) else "empty_init"},
        storage=storage,
    )

    version_marker = storage.get_version_marker(cat_path)
    return df, version_marker


def load_catalog(
    tenant_id: str,
    storage: StorageBackend | None = None,
    auto_seed: bool = True,
    who: str = "system",
) -> tuple[pd.DataFrame, str | None]:
    """Load catalog DataFrame and version marker for tenant.

    Returns:
        tuple[DataFrame, version_marker]
    """
    if storage is None:
        storage = get_storage_backend()

    cat_path = get_catalog_path(tenant_id)
    if not storage.exists(cat_path):
        if auto_seed:
            return ensure_catalog_exists(tenant_id, storage=storage, who=who)
        return pd.DataFrame(columns=STANDARD_COLUMNS), None

    try:
        content = storage.read_file(cat_path)
        if not content or not content.strip():
            df = pd.DataFrame(columns=STANDARD_COLUMNS)
        else:
            df = pd.read_csv(io.BytesIO(content), dtype={"product_id": str})
    except Exception as exc:
        logger.warning("Error reading catalog '%s': %s", cat_path, exc)
        df = pd.DataFrame(columns=STANDARD_COLUMNS)

    # Ensure required standard columns exist
    df.columns = [str(c).strip() for c in df.columns]
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = None

    if "product_id" in df.columns:
        df["product_id"] = df["product_id"].astype(str).str.strip()

    version_marker = storage.get_version_marker(cat_path)
    return df, version_marker


def save_catalog(
    tenant_id: str,
    df: pd.DataFrame,
    expected_version: str | None = None,
    who: str = "system",
    action: str = "update",
    product_ids: list[str] | None = None,
    details: dict[str, Any] | None = None,
    storage: StorageBackend | None = None,
) -> tuple[str | None, pd.DataFrame]:
    """Save catalog DataFrame with optimistic concurrency check.

    Args:
        tenant_id: Target tenant.
        df: DataFrame to save.
        expected_version: Version marker expected prior to writing.
        who: Identity making the change.
        action: Audit action name.
        product_ids: Affected product IDs.
        details: Additional context for audit log.
        storage: StorageBackend instance.

    Returns:
        tuple[new_version_marker, saved_df]

    Raises:
        ConcurrentModificationError: If expected_version is specified and does not match.
    """
    if storage is None:
        storage = get_storage_backend()

    cat_path = get_catalog_path(tenant_id)

    # Optimistic Concurrency Check
    current_version = storage.get_version_marker(cat_path)
    if expected_version is not None and current_version is not None:
        if current_version != expected_version:
            raise ConcurrentModificationError(
                f"Catalog was modified concurrently: expected version '{expected_version}' "
                f"does not match current version '{current_version}'. Please reload and try again."
            )

    # Standardize column order (standard columns first, then pass-through extras)
    standard_present = [c for c in STANDARD_COLUMNS if c in df.columns]
    extra_present = [c for c in df.columns if c not in STANDARD_COLUMNS]
    clean_df = df[standard_present + extra_present].copy()

    csv_bytes = clean_df.to_csv(index=False).encode("utf-8")
    storage.write_file(cat_path, csv_bytes)

    # Audit log
    ids_to_log = product_ids if product_ids is not None else (clean_df["product_id"].astype(str).tolist() if not clean_df.empty else [])
    record_catalog_audit(
        tenant_id=tenant_id,
        who=who,
        action=action,
        product_ids=ids_to_log,
        details=details,
        storage=storage,
    )

    new_version = storage.get_version_marker(cat_path)

    # Invalidate in-memory caches on the current worker
    try:
        from src.similarity.service import clear_similarity_cache
        clear_similarity_cache(tenant_id)
    except Exception:
        pass

    return new_version, clean_df


# ---------------------------------------------------------------------------
# Products CRUD & Filtering
# ---------------------------------------------------------------------------

def list_products(
    tenant_id: str,
    query: str | None = None,
    category: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    storage: StorageBackend | None = None,
) -> tuple[dict[str, Any], str | None]:
    """List products with search, filtering, and server-side pagination.

    Returns:
        tuple[dict response, version_marker]
    """
    df, version = load_catalog(tenant_id, storage=storage, auto_seed=True)

    if df.empty:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
        }, version

    filtered = df.copy()

    # Filter status (active | archived)
    if status and str(status).strip():
        st_clean = str(status).strip().lower()
        filtered = filtered[filtered["status"].astype(str).str.lower() == st_clean]

    # Filter category
    if category and str(category).strip():
        cat_clean = str(category).strip().lower()
        filtered = filtered[filtered["category"].astype(str).str.lower() == cat_clean]

    # Query search (case-insensitive across product_id, product_name, description, brand)
    if query and str(query).strip():
        q = str(query).strip().lower()
        mask = (
            filtered["product_id"].astype(str).str.lower().str.contains(q, regex=False)
            | filtered["product_name"].astype(str).str.lower().str.contains(q, regex=False)
            | filtered["description"].fillna("").astype(str).str.lower().str.contains(q, regex=False)
            | filtered["brand"].fillna("").astype(str).str.lower().str.contains(q, regex=False)
            | filtered["category"].astype(str).str.lower().str.contains(q, regex=False)
        )
        filtered = filtered[mask]

    total = len(filtered)
    page_size = max(1, min(100, page_size))
    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 0
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    sliced = filtered.iloc[start_idx:end_idx]
    items = [_format_product_row(row) for row in sliced.to_dict(orient="records")]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }, version


def get_catalog_summary(
    tenant_id: str,
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Calculate summary metrics for a tenant's product catalogue."""
    df, _ = load_catalog(tenant_id, storage=storage, auto_seed=True)

    if df.empty:
        return {
            "active": 0,
            "archived": 0,
            "out_of_stock": 0,
            "by_category": {},
            "products_added_since_last_training": 0,
            "products_changed_since_last_training": 0,
            "never_trained": True,
        }

    status_series = df["status"].astype(str).str.lower()
    active_df = df[status_series == "active"]
    archived_df = df[status_series == "archived"]

    active_count = len(active_df)
    archived_count = len(archived_df)

    in_stock_series = pd.to_numeric(active_df["in_stock"], errors="coerce").fillna(1).astype(int)
    out_of_stock_count = int((in_stock_series == 0).sum())

    # Category counts for active products
    cat_counts = active_df["category"].astype(str).value_counts().to_dict()

    # Products added & changed since last training
    if storage is None:
        storage = get_storage_backend()

    trained_prods_path = f"models/{tenant_id}/trained_products.json"
    status_file = f"status/{tenant_id}.json"
    last_trained_ts: str | None = None
    trained_set: set[str] = set()
    never_trained = True

    if storage.exists(trained_prods_path):
        try:
            trained_list = json.loads(storage.read_file(trained_prods_path).decode("utf-8"))
            if isinstance(trained_list, list):
                trained_set = {str(pid).strip() for pid in trained_list}
                never_trained = False
        except Exception:
            pass

    if storage.exists(status_file):
        try:
            status_data = json.loads(storage.read_file(status_file).decode("utf-8"))
            if status_data.get("status") == "completed" or status_data.get("ready"):
                last_trained_ts = status_data.get("trained_at") or status_data.get("updated_at") or status_data.get("started_at")
                if not storage.exists(trained_prods_path) and status_data.get("status") == "completed":
                    # If trained_products.json was not created (e.g. legacy model), look at dataset stats
                    never_trained = False
        except Exception:
            pass

    if never_trained:
        added_since = 0
        changed_since = 0
    else:
        active_pids = set(active_df["product_id"].astype(str).str.strip())
        if trained_set:
            added_since = len(active_pids - trained_set)
        elif last_trained_ts and "created_at" in active_df.columns:
            created_series = active_df["created_at"].fillna("").astype(str)
            added_since = int((created_series > last_trained_ts).sum())
        else:
            added_since = 0

        if last_trained_ts and "updated_at" in active_df.columns:
            updated_series = active_df["updated_at"].fillna("").astype(str)
            if trained_set:
                changed_mask = (active_df["product_id"].astype(str).str.strip().isin(trained_set)) & (updated_series > str(last_trained_ts))
            else:
                changed_mask = updated_series > str(last_trained_ts)
            changed_since = int(changed_mask.sum())
        else:
            changed_since = 0

    return {
        "active": active_count,
        "archived": archived_count,
        "out_of_stock": out_of_stock_count,
        "by_category": cat_counts,
        "products_added_since_last_training": added_since,
        "products_changed_since_last_training": changed_since,
        "never_trained": never_trained,
    }


def add_product(
    tenant_id: str,
    data: dict[str, Any],
    who: str = "system",
    expected_version: str | None = None,
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Add a new product to the catalogue.

    Raises:
        ValueError: On invalid input (missing required fields or negative price).
        DuplicateProductError: If product_id already exists.
        ConcurrentModificationError: On version mismatch.
    """
    prod_id = _clean_str(data.get("product_id"))
    if not prod_id:
        raise ValueError("Field 'product_id' is required and cannot be empty.")

    prod_name = _clean_str(data.get("product_name"))
    if not prod_name:
        raise ValueError("Field 'product_name' is required and cannot be empty.")

    category = _clean_str(data.get("category"))
    if not category:
        raise ValueError("Field 'category' is required and cannot be empty.")

    raw_price = data.get("price")
    cleaned_price = _clean_price(raw_price) if raw_price is not None else None
    if raw_price is not None and cleaned_price is None:
        raise ValueError(f"Invalid price value '{raw_price}'. Must be a non-negative number.")
    if cleaned_price is not None and cleaned_price < 0:
        raise ValueError("Price must be a non-negative number.")

    df, version = load_catalog(tenant_id, storage=storage, auto_seed=True, who=who)
    exp_ver = expected_version if expected_version is not None else version

    if not df.empty and prod_id in df["product_id"].astype(str).values:
        raise DuplicateProductError(f"Product with ID '{prod_id}' already exists in catalogue.")

    now_iso = datetime.now(timezone.utc).isoformat()
    new_row: dict[str, Any] = {
        "product_id": prod_id,
        "product_name": prod_name,
        "category": category,
        "status": "active",
        "brand": _clean_str(data.get("brand")),
        "price": cleaned_price,
        "in_stock": int(data.get("in_stock", 1)) if data.get("in_stock") is not None else 1,
        "description": _clean_str(data.get("description")),
        "image_url": _clean_str(data.get("image_url")),
        "product_url": _clean_str(data.get("product_url")),
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    # Include any custom / pass-through attributes
    for k, v in data.items():
        if k not in new_row:
            new_row[k] = v

    new_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_catalog(
        tenant_id=tenant_id,
        df=new_df,
        expected_version=exp_ver,
        who=who,
        action="create",
        product_ids=[prod_id],
        storage=storage,
    )

    return _format_product_row(new_row)


def update_product(
    tenant_id: str,
    product_id: str,
    update_data: dict[str, Any],
    who: str = "system",
    expected_version: str | None = None,
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Partially update an existing product.

    Raises:
        ProductNotFoundError: If product_id does not exist.
        ValueError: On invalid update data.
        ConcurrentModificationError: On version mismatch.
    """
    prod_id = str(product_id).strip()
    df, version = load_catalog(tenant_id, storage=storage, auto_seed=True, who=who)
    exp_ver = expected_version if expected_version is not None else version

    if df.empty or prod_id not in df["product_id"].astype(str).values:
        raise ProductNotFoundError(f"Product '{prod_id}' not found in catalogue.")

    idx = df[df["product_id"].astype(str) == prod_id].index[0]
    row = df.loc[idx].to_dict()

    if "product_name" in update_data:
        val = _clean_str(update_data["product_name"])
        if not val:
            raise ValueError("product_name cannot be empty.")
        row["product_name"] = val

    if "category" in update_data:
        val = _clean_str(update_data["category"])
        if not val:
            raise ValueError("category cannot be empty.")
        row["category"] = val

    if "price" in update_data:
        val = update_data["price"]
        cleaned_price = _clean_price(val) if val is not None else None
        if val is not None and cleaned_price is None:
            raise ValueError(f"Invalid price value '{val}'.")
        if cleaned_price is not None and cleaned_price < 0:
            raise ValueError("Price must be a non-negative number.")
        row["price"] = cleaned_price

    if "in_stock" in update_data:
        try:
            row["in_stock"] = int(update_data["in_stock"])
        except (ValueError, TypeError):
            row["in_stock"] = 1

    if "status" in update_data:
        st = str(update_data["status"]).strip().lower()
        if st not in ("active", "archived"):
            raise ValueError("status must be 'active' or 'archived'.")
        row["status"] = st

    for field in ("brand", "description", "image_url", "product_url"):
        if field in update_data:
            row[field] = _clean_str(update_data[field])

    # Pass-through extra attributes
    for k, v in update_data.items():
        if k not in STANDARD_COLUMNS:
            row[k] = v

    row["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Assign updated row back
    for col in row.keys():
        if col not in df.columns:
            df[col] = None
    for col, val in row.items():
        if val is not None and df[col].dtype != "object" and not isinstance(val, (int, float)):
            df[col] = df[col].astype("object")
        df.loc[idx, col] = val

    save_catalog(
        tenant_id=tenant_id,
        df=df,
        expected_version=exp_ver,
        who=who,
        action="update",
        product_ids=[prod_id],
        storage=storage,
    )

    return _format_product_row(row)


def delete_product(
    tenant_id: str,
    product_id: str,
    permanent: bool = False,
    who: str = "system",
    expected_version: str | None = None,
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Soft delete (archive) or permanently delete a product.

    Permanent delete is only permitted for products already in 'archived' status.
    """
    prod_id = str(product_id).strip()
    df, version = load_catalog(tenant_id, storage=storage, auto_seed=True, who=who)
    exp_ver = expected_version if expected_version is not None else version

    if df.empty or prod_id not in df["product_id"].astype(str).values:
        raise ProductNotFoundError(f"Product '{prod_id}' not found in catalogue.")

    idx = df[df["product_id"].astype(str) == prod_id].index[0]
    current_status = str(df.at[idx, "status"]).strip().lower()

    if permanent:
        if current_status != "archived":
            raise InvalidOperationError(
                f"Product '{prod_id}' is active. Only already-archived products can be permanently deleted. "
                f"Archive the product first with a normal DELETE request."
            )
        # Drop row entirely
        df = df.drop(index=idx).reset_index(drop=True)
        save_catalog(
            tenant_id=tenant_id,
            df=df,
            expected_version=exp_ver,
            who=who,
            action="permanent_delete",
            product_ids=[prod_id],
            storage=storage,
        )
        return {
            "message": f"Product '{prod_id}' permanently deleted from catalogue.",
            "product_id": prod_id,
            "status": "deleted",
        }
    else:
        # Soft delete: set status to archived
        df.at[idx, "status"] = "archived"
        df.at[idx, "updated_at"] = datetime.now(timezone.utc).isoformat()
        save_catalog(
            tenant_id=tenant_id,
            df=df,
            expected_version=exp_ver,
            who=who,
            action="archive",
            product_ids=[prod_id],
            storage=storage,
        )
        return {
            "message": f"Product '{prod_id}' archived.",
            "product_id": prod_id,
            "status": "archived",
        }


def restore_product(
    tenant_id: str,
    product_id: str,
    who: str = "system",
    expected_version: str | None = None,
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Restore an archived product to active status."""
    prod_id = str(product_id).strip()
    df, version = load_catalog(tenant_id, storage=storage, auto_seed=True, who=who)
    exp_ver = expected_version if expected_version is not None else version

    if df.empty or prod_id not in df["product_id"].astype(str).values:
        raise ProductNotFoundError(f"Product '{prod_id}' not found in catalogue.")

    idx = df[df["product_id"].astype(str) == prod_id].index[0]
    df.at[idx, "status"] = "active"
    df.at[idx, "updated_at"] = datetime.now(timezone.utc).isoformat()

    save_catalog(
        tenant_id=tenant_id,
        df=df,
        expected_version=exp_ver,
        who=who,
        action="restore",
        product_ids=[prod_id],
        storage=storage,
    )

    return {
        "message": f"Product '{prod_id}' restored to active status.",
        "product_id": prod_id,
        "status": "active",
    }


def bulk_action(
    tenant_id: str,
    action: str,
    product_ids: list[str],
    who: str = "system",
    expected_version: str | None = None,
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Perform bulk action ('archive', 'restore', 'delete') on a list of product IDs (max 500)."""
    clean_action = str(action).strip().lower()
    if clean_action not in ("archive", "restore", "delete"):
        raise ValueError("Bulk action must be one of 'archive', 'restore', or 'delete'.")

    clean_ids = [str(pid).strip() for pid in product_ids if str(pid).strip()]
    if not clean_ids:
        return {"action": clean_action, "affected": 0, "product_ids": []}

    if len(clean_ids) > 500:
        raise ValueError(f"Bulk operations are limited to a maximum of 500 product IDs. Got {len(clean_ids)}.")

    df, version = load_catalog(tenant_id, storage=storage, auto_seed=True, who=who)
    exp_ver = expected_version if expected_version is not None else version

    if df.empty:
        return {"action": clean_action, "affected": 0, "product_ids": []}

    now_iso = datetime.now(timezone.utc).isoformat()
    affected_ids: list[str] = []

    if clean_action == "archive":
        mask = df["product_id"].astype(str).isin(clean_ids)
        affected_ids = df.loc[mask, "product_id"].astype(str).tolist()
        df.loc[mask, "status"] = "archived"
        df.loc[mask, "updated_at"] = now_iso

    elif clean_action == "restore":
        mask = df["product_id"].astype(str).isin(clean_ids)
        affected_ids = df.loc[mask, "product_id"].astype(str).tolist()
        df.loc[mask, "status"] = "active"
        df.loc[mask, "updated_at"] = now_iso

    elif clean_action == "delete":
        # Only permanently delete items that are ALREADY archived
        mask = (
            df["product_id"].astype(str).isin(clean_ids)
            & (df["status"].astype(str).str.lower() == "archived")
        )
        affected_ids = df.loc[mask, "product_id"].astype(str).tolist()
        df = df[~mask].reset_index(drop=True)

    if affected_ids:
        save_catalog(
            tenant_id=tenant_id,
            df=df,
            expected_version=exp_ver,
            who=who,
            action=f"bulk_{clean_action}",
            product_ids=affected_ids,
            storage=storage,
        )

    return {
        "action": clean_action,
        "affected": len(affected_ids),
        "product_ids": affected_ids,
    }


def generate_catalog_template(format: str = "csv") -> str:
    """Generate sample catalogue CSV template with headers and example row."""
    lines = [
        ",".join(STANDARD_COLUMNS[:10]),
        "PROD-001,Wireless Noise-Canceling Headphones,Electronics,active,AcroSound,199.99,1,"
        "Premium over-ear wireless headphones with ANC,https://example.com/images/prod-001.jpg,"
        "https://example.com/products/prod-001",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Upload Parsing, Preview & Commit Pipeline
# ---------------------------------------------------------------------------

def _parse_xlsx_content(content: bytes) -> list[dict[str, Any]]:
    """Parse XLSX binary content into a list of row dicts without third-party dependencies."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            # 1. Parse shared strings if present
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in z.namelist():
                ss_tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for elem in ss_tree:
                    if elem.tag.endswith("}si") or elem.tag == "si":
                        texts = [
                            t.text for t in elem.iter()
                            if (t.tag.endswith("}t") or t.tag == "t") and t.text
                        ]
                        shared_strings.append("".join(texts))

            # 2. Parse sheet1.xml
            sheet_path = "xl/worksheets/sheet1.xml"
            if sheet_path not in z.namelist():
                # find first sheet
                for name in z.namelist():
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                        sheet_path = name
                        break

            sheet_tree = ET.fromstring(z.read(sheet_path))
            rows: list[list[str]] = []

            for row_elem in sheet_tree.iter():
                if not (row_elem.tag.endswith("}row") or row_elem.tag == "row"):
                    continue
                row_cells: list[str] = []
                for c_elem in row_elem:
                    if not (c_elem.tag.endswith("}c") or c_elem.tag == "c"):
                        continue
                    cell_type = c_elem.attrib.get("t")
                    val = ""
                    for child in c_elem:
                        if child.tag.endswith("}v") or child.tag == "v":
                            raw_v = child.text or ""
                            if cell_type == "s":
                                try:
                                    s_idx = int(raw_v)
                                    val = shared_strings[s_idx] if s_idx < len(shared_strings) else raw_v
                                except ValueError:
                                    val = raw_v
                            else:
                                val = raw_v
                        elif child.tag.endswith("}is") or child.tag == "is":
                            texts = [
                                t.text for t in child.iter()
                                if (t.tag.endswith("}t") or t.tag == "t") and t.text
                            ]
                            val = "".join(texts)
                    row_cells.append(val)
                if row_cells:
                    rows.append(row_cells)

            if not rows:
                return []

            headers = [str(h).strip() for h in rows[0]]
            records: list[dict[str, Any]] = []
            for r in rows[1:]:
                rec = {}
                for idx, col in enumerate(headers):
                    rec[col] = r[idx] if idx < len(r) else None
                records.append(rec)
            return records
    except Exception as exc:
        raise ValueError(f"Failed to parse XLSX file: {exc}") from exc


def parse_and_preview_upload(
    tenant_id: str,
    file_bytes: bytes,
    filename: str,
    mode: str = "upsert",
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Parse uploaded catalogue file (CSV, JSON, XLSX), validate, and generate preview diff.

    Validation rules:
    - Max size 20 MB.
    - Max 100,000 rows.
    - Required columns: product_id, product_name, category.
    - Duplicate product_ids within file are reported with row numbers.
    - Trimmed product_id cannot be empty.
    - Numeric price >= 0.

    Returns:
        dict: {upload_id, mode, to_add, to_update, to_archive, total_rows, errors}
    """
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise ValueError(
            f"File size ({len(file_bytes) / 1024 / 1024:.1f} MB) exceeds maximum allowed size of 20 MB."
        )

    clean_mode = str(mode).strip().lower()
    if clean_mode not in ("upsert", "replace"):
        raise ValueError("Upload mode must be 'upsert' or 'replace'.")

    lower_name = filename.lower()
    raw_records: list[dict[str, Any]] = []

    # 1. Parse File Content
    if lower_name.endswith(".xlsx"):
        raw_records = _parse_xlsx_content(file_bytes)
    elif lower_name.endswith(".json"):
        try:
            parsed = parse_catalog_feed(file_bytes, content_type="application/json")
            if parsed:
                raw_records = parsed
            else:
                text = file_bytes.decode("utf-8")
                loaded = json.loads(text)
                if isinstance(loaded, list):
                    raw_records = loaded
                elif isinstance(loaded, dict):
                    for k in ("products", "items", "data", "catalog"):
                        if k in loaded and isinstance(loaded[k], list):
                            raw_records = loaded[k]
                            break
        except Exception as exc:
            raise ValueError(f"Invalid JSON file format: {exc}") from exc
    else:
        # Default to CSV
        try:
            df_in = pd.read_csv(io.BytesIO(file_bytes))
            raw_records = df_in.to_dict(orient="records")
        except Exception as exc:
            raise ValueError(f"Invalid CSV file format: {exc}") from exc

    if len(raw_records) > MAX_UPLOAD_ROWS:
        raise ValueError(
            f"File row count ({len(raw_records):,}) exceeds maximum limit of {MAX_UPLOAD_ROWS:,} rows."
        )

    # 2. Row Validation and Error Collection
    errors: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}  # prod_id -> first row number seen

    # Row numbers: 1 is header, data starts at row 2
    for idx, rec in enumerate(raw_records, start=2):
        row_num = idx
        raw_pid = rec.get("product_id")
        raw_name = rec.get("product_name") or rec.get("title") or rec.get("name")
        raw_cat = rec.get("category") or rec.get("product_type")
        raw_price = rec.get("price")

        row_errors: list[str] = []

        # Validate product_id
        if raw_pid is None or pd.isna(raw_pid):
            row_errors.append("Missing required column 'product_id'")
            pid = None
        else:
            pid = str(raw_pid).strip()
            if not pid or pid.lower() in ("nan", "none", "null"):
                row_errors.append("product_id cannot be empty")
                pid = None

        # Check duplicate IDs within the file
        if pid:
            if pid in seen_ids:
                row_errors.append(
                    f"Duplicate product_id '{pid}' in file (first seen on row {seen_ids[pid]})"
                )
            else:
                seen_ids[pid] = row_num

        # Validate product_name
        if raw_name is None or pd.isna(raw_name) or not str(raw_name).strip():
            row_errors.append("Missing required column 'product_name'")
            name = None
        else:
            name = str(raw_name).strip()

        # Validate category
        if raw_cat is None or pd.isna(raw_cat) or not str(raw_cat).strip():
            row_errors.append("Missing required column 'category'")
            cat = None
        else:
            cat = str(raw_cat).strip()

        # Validate price
        cleaned_price = None
        if raw_price is not None and not pd.isna(raw_price):
            cleaned_price = _clean_price(raw_price)
            if cleaned_price is None:
                row_errors.append(f"Invalid price '{raw_price}': must be a numeric value")
            elif cleaned_price < 0:
                row_errors.append(f"Invalid price '{raw_price}': must be non-negative (>= 0)")

        if row_errors:
            for err in row_errors:
                errors.append({"row": row_num, "message": err})
        else:
            clean_rec = dict(rec)
            clean_rec["product_id"] = pid
            clean_rec["product_name"] = name
            clean_rec["category"] = cat
            clean_rec["price"] = cleaned_price
            valid_rows.append(clean_rec)

    # 3. Diff Calculation against Current Catalogue
    if storage is None:
        storage = get_storage_backend()

    existing_df, _ = load_catalog(tenant_id, storage=storage, auto_seed=True)
    if not existing_df.empty:
        existing_ids = set(existing_df["product_id"].astype(str))
        active_ids = set(
            existing_df[existing_df["status"].astype(str).str.lower() == "active"]["product_id"].astype(str)
        )
    else:
        existing_ids = set()
        active_ids = set()

    file_valid_ids = {r["product_id"] for r in valid_rows}
    to_add = len(file_valid_ids - existing_ids)
    to_update = len(file_valid_ids.intersection(existing_ids))
    to_archive = len(active_ids - file_valid_ids) if clean_mode == "replace" else 0

    # 4. Store Pending Upload Record
    upload_id = secrets.token_hex(16)
    expires_at = datetime.now(timezone.utc).timestamp() + PENDING_EXPIRATION_SECONDS
    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    pending_record = {
        "upload_id": upload_id,
        "tenant_id": tenant_id,
        "mode": clean_mode,
        "filename": filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at_iso,
        "expires_at_ts": expires_at,
        "to_add": to_add,
        "to_update": to_update,
        "to_archive": to_archive,
        "total_rows": len(valid_rows),
        "valid_rows": valid_rows,
        "errors_count": len(errors),
    }

    pending_path = get_pending_path(tenant_id, upload_id)
    storage.write_file(pending_path, json.dumps(pending_record, ensure_ascii=False).encode("utf-8"))

    return {
        "upload_id": upload_id,
        "mode": clean_mode,
        "to_add": to_add,
        "to_update": to_update,
        "to_archive": to_archive,
        "total_rows": len(valid_rows),
        "errors": errors,
    }


def commit_upload(
    tenant_id: str,
    upload_id: str,
    who: str = "system",
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Commit a pending previewed upload to the catalogue with snapshotting."""
    if storage is None:
        storage = get_storage_backend()

    pending_path = get_pending_path(tenant_id, upload_id)
    if not storage.exists(pending_path):
        raise ProductNotFoundError(f"Pending upload '{upload_id}' not found.")

    pending_data = json.loads(storage.read_file(pending_path).decode("utf-8"))
    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts > pending_data.get("expires_at_ts", 0):
        storage.delete_file(pending_path)
        raise InvalidOperationError("Pending upload has expired (valid for 1 hour). Please upload again.")

    valid_rows = pending_data.get("valid_rows", [])
    mode = pending_data.get("mode", "upsert")

    # 1. Load Current Catalog & Take Pre-Commit Snapshot
    current_df, version = load_catalog(tenant_id, storage=storage, auto_seed=True)
    now_iso = datetime.now(timezone.utc).isoformat()

    snapshot_ts = int(time.time() * 1000)
    snapshot_name = f"snapshot-{snapshot_ts}-{upload_id}.csv"
    snapshot_path = f"data/catalog/{tenant_id}/snapshots/{snapshot_name}"

    # Write snapshot
    if not current_df.empty:
        snapshot_bytes = current_df.to_csv(index=False).encode("utf-8")
        storage.write_file(snapshot_path, snapshot_bytes)
    else:
        empty_df = pd.DataFrame(columns=STANDARD_COLUMNS)
        storage.write_file(snapshot_path, empty_df.to_csv(index=False).encode("utf-8"))

    # Prune snapshots: keep only the last MAX_SNAPSHOTS
    try:
        snapshots_prefix = get_snapshots_prefix(tenant_id)
        snapshot_files = sorted(storage.list_files(snapshots_prefix), reverse=True)
        for old_snap in snapshot_files[MAX_SNAPSHOTS:]:
            storage.delete_file(old_snap)
    except Exception as exc:
        logger.warning("Failed pruning snapshots for tenant '%s': %s", tenant_id, exc)

    # 2. Apply Upload Rows
    file_df = pd.DataFrame(valid_rows)
    if file_df.empty:
        storage.delete_file(pending_path)
        return {
            "status": "committed",
            "upload_id": upload_id,
            "mode": mode,
            "applied": 0,
            "added": 0,
            "updated": 0,
            "archived": 0,
        }

    file_df["product_id"] = file_df["product_id"].astype(str).str.strip()
    if "status" not in file_df.columns:
        file_df["status"] = "active"
    else:
        file_df["status"] = file_df["status"].fillna("active").astype(str)

    if "in_stock" not in file_df.columns:
        file_df["in_stock"] = 1
    else:
        file_df["in_stock"] = pd.to_numeric(file_df["in_stock"], errors="coerce").fillna(1).astype(int)

    file_df["updated_at"] = now_iso

    file_ids = set(file_df["product_id"])

    if current_df.empty or "product_id" not in current_df.columns:
        file_df["created_at"] = now_iso
        final_df = file_df
        added_count = len(file_df)
        updated_count = 0
        archived_count = 0
    else:
        current_ids = set(current_df["product_id"].astype(str))
        updated_count = len(file_ids.intersection(current_ids))
        added_count = len(file_ids - current_ids)

        # In replace mode: active products missing from the file are ARCHIVED (never deleted)
        if mode == "replace":
            active_missing = (
                current_df["status"].astype(str).str.lower() == "active"
            ) & (~current_df["product_id"].astype(str).isin(file_ids))
            archived_count = int(active_missing.sum())
            current_df.loc[active_missing, "status"] = "archived"
            current_df.loc[active_missing, "updated_at"] = now_iso
        else:
            archived_count = 0

        # Preserve untouched existing rows
        untouched = current_df[~current_df["product_id"].astype(str).isin(file_ids)].copy()

        # For rows to add: assign created_at
        to_add_mask = ~file_df["product_id"].isin(current_ids)
        file_df.loc[to_add_mask, "created_at"] = now_iso

        # For rows to update: preserve their original created_at from current_df
        to_update_mask = file_df["product_id"].isin(current_ids)
        if to_update_mask.any():
            created_map = current_df.set_index("product_id")["created_at"].to_dict()
            file_df.loc[to_update_mask, "created_at"] = file_df.loc[to_update_mask, "product_id"].map(created_map)

        final_df = pd.concat([untouched, file_df], ignore_index=True)

    # Deduplicate keeping last
    final_df = final_df.drop_duplicates(subset=["product_id"], keep="last").reset_index(drop=True)

    # 3. Save to Storage
    save_catalog(
        tenant_id=tenant_id,
        df=final_df,
        expected_version=version,
        who=who,
        action="upload_commit",
        product_ids=list(file_ids),
        details={"upload_id": upload_id, "mode": mode, "snapshot": snapshot_name},
        storage=storage,
    )

    # Delete pending upload
    storage.delete_file(pending_path)

    return {
        "status": "committed",
        "upload_id": upload_id,
        "mode": mode,
        "applied": len(file_ids),
        "added": added_count,
        "updated": updated_count,
        "archived": archived_count,
    }


def undo_last_commit(
    tenant_id: str,
    who: str = "system",
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Restore the snapshot taken before the last commit."""
    if storage is None:
        storage = get_storage_backend()

    prefix = get_snapshots_prefix(tenant_id)
    snapshots = sorted(storage.list_files(prefix), reverse=True)

    if not snapshots:
        raise SnapshotError("No snapshot available to undo.")

    latest_snapshot = snapshots[0]
    try:
        snapshot_bytes = storage.read_file(latest_snapshot)
        snapshot_df = pd.read_csv(io.BytesIO(snapshot_bytes))
    except Exception as exc:
        raise SnapshotError(f"Failed to read snapshot '{latest_snapshot}': {exc}") from exc

    _, current_version = load_catalog(tenant_id, storage=storage, auto_seed=False)

    save_catalog(
        tenant_id=tenant_id,
        df=snapshot_df,
        expected_version=current_version,
        who=who,
        action="undo",
        product_ids=snapshot_df["product_id"].astype(str).tolist() if not snapshot_df.empty else [],
        details={"restored_from": latest_snapshot},
        storage=storage,
    )

    # Remove the used snapshot
    storage.delete_file(latest_snapshot)

    return {
        "status": "restored",
        "snapshot": os.path.basename(latest_snapshot),
        "message": "Catalogue successfully restored from pre-commit snapshot.",
        "total_products": len(snapshot_df),
    }

