"""In-memory cached active product set for tenant-managed product catalogue.

Provides `get_active_catalog(tenant_id, storage)` returning a dictionary mapping
active `product_id` to its metadata (product_id, product_name, category, price,
image_url, in_stock, brand, etc.).

Cache coherency:
- Maintained per tenant in memory.
- Checks storage version marker at most once every 15 seconds (cheap version check,
  never a full file read per request), allowing updates made by other workers or processes
  to be picked up without restarting.
- If tenant has no catalog.csv, returns None (indicating NO filtering for backward compatibility).
- Does NOT trigger first-access seeding from the recommendation hot path.
- Respects `catalog.hide_out_of_stock` (default: True).
"""

from __future__ import annotations

import io
import logging
import threading
import time
from typing import Any

import pandas as pd

from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import load_config

logger = logging.getLogger(__name__)

# In-memory tenant active catalog cache: {tenant_id: {product_id: product_dict}}
_ACTIVE_CATALOG_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
# Cache metadata: {tenant_id: {"version_marker": marker, "last_checked": float, "exists": bool}}
_ACTIVE_METADATA: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()

CACHE_TTL_SECONDS = 15.0


def clear_active_catalog_cache(tenant_id: str | None = None) -> None:
    """Clear cached active catalog for a specific tenant or all tenants."""
    with _CACHE_LOCK:
        if tenant_id is None:
            _ACTIVE_CATALOG_CACHE.clear()
            _ACTIVE_METADATA.clear()
        else:
            _ACTIVE_CATALOG_CACHE.pop(tenant_id, None)
            _ACTIVE_METADATA.pop(tenant_id, None)


def _should_hide_out_of_stock() -> bool:
    """Read catalog.hide_out_of_stock setting from config, defaulting to True."""
    try:
        cfg = load_config()
        cat_cfg = cfg.get("catalog", {})
        if isinstance(cat_cfg, dict):
            return cat_cfg.get("hide_out_of_stock", True)
    except Exception:
        pass
    return True


def get_active_catalog(
    tenant_id: str,
    storage: StorageBackend | None = None,
    hide_out_of_stock: bool | None = None,
) -> dict[str, dict[str, Any]] | None:
    """Retrieve mapping of active products for a tenant.

    Args:
        tenant_id: Tenant identifier.
        storage: StorageBackend instance.
        hide_out_of_stock: Optional override; if None, reads from config (default True).

    Returns:
        dict[product_id, product_dict] if catalog.csv exists; None if no catalog.csv exists.
    """
    now = time.monotonic()

    with _CACHE_LOCK:
        meta = _ACTIVE_METADATA.get(tenant_id)

        # 1. Check TTL: if checked within 15 seconds, return cached value immediately
        if (
            meta is not None
            and (now - meta.get("last_checked", 0.0) < CACHE_TTL_SECONDS)
            and (hide_out_of_stock is None or hide_out_of_stock == meta.get("hide_out_of_stock"))
        ):
            if not meta.get("exists", True):
                return None
            return _ACTIVE_CATALOG_CACHE.get(tenant_id)

    if storage is None:
        storage = get_storage_backend()

    if hide_out_of_stock is None:
        hide_out_of_stock = _should_hide_out_of_stock()

    cat_path = f"data/catalog/{tenant_id}/catalog.csv"

    # 2. Check existence in storage (no auto-seeding on recommendation path!)
    if not storage.exists(cat_path):
        with _CACHE_LOCK:
            _ACTIVE_METADATA[tenant_id] = {
                "version_marker": None,
                "last_checked": now,
                "exists": False,
            }
            _ACTIVE_CATALOG_CACHE.pop(tenant_id, None)
        return None

    # 3. Check version marker (cheap check, avoids full file read if unchanged)
    current_marker = storage.get_version_marker(cat_path)
    with _CACHE_LOCK:
        meta = _ACTIVE_METADATA.get(tenant_id)
        if (
            meta is not None
            and meta.get("exists", False)
            and current_marker is not None
            and current_marker == meta.get("version_marker")
            and tenant_id in _ACTIVE_CATALOG_CACHE
        ):
            meta["last_checked"] = now
            return _ACTIVE_CATALOG_CACHE[tenant_id]

    # 4. Marker changed or first load: read catalog.csv
    try:
        content = storage.read_file(cat_path)
        if not content or not content.strip():
            df = pd.DataFrame()
        else:
            df = pd.read_csv(io.BytesIO(content), dtype={"product_id": str})
    except Exception as exc:
        logger.warning("Error reading catalog for active set '%s': %s", cat_path, exc)
        df = pd.DataFrame()

    active_map: dict[str, dict[str, Any]] = {}
    if not df.empty and "product_id" in df.columns:
        df["product_id"] = df["product_id"].astype(str).str.strip()
        status_col = (
            df["status"].astype(str).str.lower().str.strip()
            if "status" in df.columns
            else pd.Series("active", index=df.index)
        )

        mask = status_col == "active"

        if hide_out_of_stock and "in_stock" in df.columns:
            in_stock_num = pd.to_numeric(df["in_stock"], errors="coerce").fillna(1).astype(int)
            mask = mask & (in_stock_num != 0)

        active_df = df[mask]

        # Extract rows into product dicts
        for rec in active_df.to_dict(orient="records"):
            pid = rec.get("product_id")
            if not pid or pd.isna(pid):
                continue
            pid_str = str(pid).strip()

            p_name = rec.get("product_name") or rec.get("title") or rec.get("name") or pid_str
            if pd.isna(p_name):
                p_name = pid_str

            cat = rec.get("category") or rec.get("product_type")
            if pd.isna(cat):
                cat = None

            raw_price = rec.get("price")
            try:
                price_val = float(raw_price) if raw_price is not None and not pd.isna(raw_price) else None
            except (ValueError, TypeError):
                price_val = None

            raw_in_stock = rec.get("in_stock")
            try:
                stock_val = int(raw_in_stock) if raw_in_stock is not None and not pd.isna(raw_in_stock) else 1
            except (ValueError, TypeError):
                stock_val = 1

            img_url = rec.get("image_url")
            if pd.isna(img_url):
                img_url = None

            brand_val = rec.get("brand")
            if pd.isna(brand_val):
                brand_val = None

            active_map[pid_str] = {
                "product_id": pid_str,
                "product_name": str(p_name).strip(),
                "category": str(cat).strip() if cat else None,
                "price": price_val,
                "image_url": str(img_url).strip() if img_url else None,
                "in_stock": stock_val,
                "brand": str(brand_val).strip() if brand_val else None,
            }

    with _CACHE_LOCK:
        _ACTIVE_METADATA[tenant_id] = {
            "version_marker": current_marker,
            "last_checked": now,
            "exists": True,
            "hide_out_of_stock": hide_out_of_stock,
        }
        _ACTIVE_CATALOG_CACHE[tenant_id] = active_map

    return active_map

