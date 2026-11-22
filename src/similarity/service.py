"""Similarity service layer for tenant product recommendations.

Provides:
- In-memory cached SimilarityIndex per tenant with 15-second version marker re-checking.
- Support for tenants with a managed catalogue and backward-compatible fallback to processed products.csv.
- Cosine similarity computation via sparse matrix-vector product.
- Filter enforcement: self-exclusion, status/stock, same_category, and max_price_ratio.
- Bounded memory partition for large catalogues (> 100,000 items).
- Deterministic reason generation and popularity top-up for sparse catalogues.
"""

from __future__ import annotations

from collections import Counter
import io
import logging
import math
import secrets
import threading
import time
from typing import Any

import numpy as np
import pandas as pd

from src.catalog.active_set import get_active_catalog
from src.similarity.feature_matrix import SimilarityIndex, build_similarity_index
from src.similarity.specs_parser import format_human_readable_specs
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import load_config

logger = logging.getLogger(__name__)

_SIMILARITY_CACHE: dict[str, SimilarityIndex] = {}
_SIMILARITY_METADATA: dict[str, dict[str, Any]] = {}
_SIMILARITY_LOCK = threading.Lock()
_TENANT_BUILD_LOCKS: dict[str, threading.Lock] = {}
_TENANT_BUILD_LOCKS_LOCK = threading.Lock()
_CONFIG_CACHE: dict[str, Any] | None = None

CACHE_TTL_SECONDS = 15.0
MAX_UNBOUNDED_CATALOG_SIZE = 100_000
LARGE_CATALOG_THRESHOLD = 10_000


def _get_tenant_build_lock(tenant_id: str) -> threading.Lock:
    """Retrieve or create a reentrant build lock for single-flight index generation."""
    with _TENANT_BUILD_LOCKS_LOCK:
        if tenant_id not in _TENANT_BUILD_LOCKS:
            _TENANT_BUILD_LOCKS[tenant_id] = threading.Lock()
        return _TENANT_BUILD_LOCKS[tenant_id]


def _get_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return provided config or cached default config to avoid repeated disk reads."""
    if config is not None:
        return config
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_config()
    return _CONFIG_CACHE


def clear_similarity_cache(tenant_id: str | None = None) -> None:
    """Clear similarity index cache for a single tenant or all tenants."""
    global _CONFIG_CACHE
    with _SIMILARITY_LOCK:
        if tenant_id is None:
            _SIMILARITY_CACHE.clear()
            _SIMILARITY_METADATA.clear()
            _CONFIG_CACHE = None
        else:
            for k in list(_SIMILARITY_CACHE.keys()):
                if k == tenant_id or k.startswith(f"{tenant_id}__"):
                    _SIMILARITY_CACHE.pop(k, None)
                    _SIMILARITY_METADATA.pop(k, None)


def _load_products_from_processed(
    tenant_id: str,
    storage: StorageBackend,
) -> list[dict[str, Any]]:
    """Read data/processed/{tenant}/products.csv read-only for tenants without a catalogue."""
    proc_path = f"data/processed/{tenant_id}/products.csv"
    if not storage.exists(proc_path) and tenant_id == "telco_default":
        if storage.exists("data/processed/products.csv"):
            proc_path = "data/processed/products.csv"

    if not storage.exists(proc_path):
        return []

    try:
        content = storage.read_file(proc_path)
        if not content or not content.strip():
            return []
        df = pd.read_csv(io.BytesIO(content), dtype={"product_id": str})
        if df.empty:
            return []

        # Standardize column names
        norm_map = {}
        for col in df.columns:
            cl = str(col).strip().lower()
            if cl in ("item_id", "stockcode", "id") and "product_id" not in df.columns:
                norm_map[col] = "product_id"
            elif cl in ("title", "name", "description") and "product_name" not in df.columns:
                norm_map[col] = "product_name"
            elif cl in ("product_type",) and "category" not in df.columns:
                norm_map[col] = "category"
        if norm_map:
            df = df.rename(columns=norm_map)

        if "product_id" not in df.columns:
            return []

        products: list[dict[str, Any]] = []
        for rec in df.to_dict(orient="records"):
            pid = rec.get("product_id")
            if not pid or pd.isna(pid):
                continue
            pid_str = str(pid).strip()

            p_entry = {k: (None if pd.isna(v) else v) for k, v in rec.items()}
            p_entry["product_id"] = pid_str
            p_entry["product_name"] = str(rec.get("product_name") or pid_str).strip()
            p_entry["category"] = str(rec.get("category")).strip() if rec.get("category") and not pd.isna(rec.get("category")) else None

            raw_price = rec.get("price")
            try:
                p_entry["price"] = float(raw_price) if raw_price is not None and not pd.isna(raw_price) else None
            except (ValueError, TypeError):
                p_entry["price"] = None

            raw_stock = rec.get("in_stock")
            try:
                p_entry["in_stock"] = int(raw_stock) if raw_stock is not None and not pd.isna(raw_stock) else 1
            except (ValueError, TypeError):
                p_entry["in_stock"] = 1

            p_entry["brand"] = str(rec.get("brand")).strip() if rec.get("brand") and not pd.isna(rec.get("brand")) else None
            p_entry["image_url"] = str(rec.get("image_url")).strip() if rec.get("image_url") and not pd.isna(rec.get("image_url")) else None
            products.append(p_entry)

        return products
    except Exception as exc:
        logger.warning("[%s] Failed reading processed products for similarity: %s", tenant_id, exc)
        return []


def get_similarity_index(
    tenant_id: str,
    storage: StorageBackend | None = None,
    config: dict[str, Any] | None = None,
    category: str | None = None,
) -> SimilarityIndex:
    """Retrieve or build the in-memory SimilarityIndex for a tenant with 15s TTL version checks.

    Uses per-tenant single-flight locking so concurrent cold requests build the index once.
    When catalogue size > 10,000 and category is specified, builds lazy-per-category to
    keep cold build times well under 1 second.
    """
    now = time.monotonic()
    norm_cat = str(category).strip().lower() if category and str(category).strip() else None
    cache_key = f"{tenant_id}__cat__{norm_cat}" if norm_cat else tenant_id

    # Fast path: in-memory cache hit within TTL without any I/O or locking
    with _SIMILARITY_LOCK:
        for ck in (cache_key, tenant_id):
            meta = _SIMILARITY_METADATA.get(ck)
            if (
                meta is not None
                and (now - meta.get("last_checked", 0.0) < CACHE_TTL_SECONDS)
                and ck in _SIMILARITY_CACHE
            ):
                return _SIMILARITY_CACHE[ck]

    # Single-flight per-tenant build lock
    tenant_lock = _get_tenant_build_lock(tenant_id)
    with tenant_lock:
        now = time.monotonic()
        # Double check after acquiring lock
        with _SIMILARITY_LOCK:
            for ck in (cache_key, tenant_id):
                meta = _SIMILARITY_METADATA.get(ck)
                if (
                    meta is not None
                    and (now - meta.get("last_checked", 0.0) < CACHE_TTL_SECONDS)
                    and ck in _SIMILARITY_CACHE
                ):
                    return _SIMILARITY_CACHE[ck]

        cfg = _get_config(config)
        if storage is None:
            storage = get_storage_backend(cfg)

        cat_path = f"data/catalog/{tenant_id}/catalog.csv"
        has_catalog = storage.exists(cat_path)

        active_path = cat_path if has_catalog else f"data/processed/{tenant_id}/products.csv"
        if not has_catalog and not storage.exists(active_path) and tenant_id == "telco_default":
            if storage.exists("data/processed/products.csv"):
                active_path = "data/processed/products.csv"

        # Check version marker
        current_marker = storage.get_version_marker(active_path) if storage.exists(active_path) else None

        with _SIMILARITY_LOCK:
            for ck in (cache_key, tenant_id):
                meta = _SIMILARITY_METADATA.get(ck)
                if (
                    meta is not None
                    and current_marker is not None
                    and current_marker == meta.get("version_marker")
                    and ck in _SIMILARITY_CACHE
                ):
                    meta["last_checked"] = now
                    return _SIMILARITY_CACHE[ck]

        # Rebuild index
        if has_catalog:
            active_map = get_active_catalog(tenant_id, storage=storage) or {}
            products_list = list(active_map.values())
        else:
            products_list = _load_products_from_processed(tenant_id, storage=storage)

        # Lazy-per-category build if catalogue is large (> 10,000 items) and category requested
        target_ck = tenant_id
        if len(products_list) > LARGE_CATALOG_THRESHOLD and norm_cat:
            filtered_list = [
                p for p in products_list
                if str(p.get("category") or "").strip().lower() == norm_cat
            ]
            if len(filtered_list) > 0:
                products_list = filtered_list
                target_ck = cache_key

        new_index = build_similarity_index(tenant_id, products_list, config=cfg)

        with _SIMILARITY_LOCK:
            _SIMILARITY_METADATA[target_ck] = {
                "version_marker": current_marker,
                "last_checked": now,
                "has_catalog": has_catalog,
            }
            _SIMILARITY_CACHE[target_ck] = new_index

        return new_index


def _get_active_popular_product_ids(
    tenant_id: str,
    category: str | None,
    exclude_ids: set[str],
    needed: int,
    active_products: dict[str, dict[str, Any]],
    storage: StorageBackend,
    same_category: bool = True,
    target_price: float | None = None,
    max_price_ratio: float = 2.0,
) -> list[str]:
    """Retrieve active popular product IDs matching category and price constraints."""
    counter: Counter[str] = Counter()

    # Read interactions
    interactions_path = f"data/processed/{tenant_id}/interactions.csv"
    if storage.exists(interactions_path):
        try:
            content = storage.read_file(interactions_path)
            idf = pd.read_csv(io.BytesIO(content))
            prod_col = "product_id" if "product_id" in idf.columns else (
                "item_id" if "item_id" in idf.columns else (
                    "StockCode" if "StockCode" in idf.columns else None
                )
            )
            if prod_col is None and len(idf.columns) >= 2:
                prod_col = idf.columns[1]
            if prod_col and prod_col in idf.columns:
                counter.update(idf[prod_col].dropna().astype(str).tolist())
        except Exception:
            pass

    # Read queued tracking events
    try:
        from src.api.tracking import get_queued_events
        for ev in get_queued_events(tenant_id):
            pid = ev.get("product_id")
            if pid:
                counter[str(pid).strip()] += 1
    except Exception:
        pass

    norm_target_cat = category.strip().lower() if category else None

    def _passes_price_filter(p_dict: dict[str, Any]) -> bool:
        if max_price_ratio <= 0 or target_price is None:
            return True
        p_val = p_dict.get("price")
        if p_val is None:
            return True
        try:
            tp = float(target_price)
            cp = float(p_val)
            if tp > 0 and cp > 0:
                return (tp / max_price_ratio) <= cp <= (tp * max_price_ratio)
        except (ValueError, TypeError):
            pass
        return True

    result: list[str] = []

    # 1. Same category popular active items
    if norm_target_cat:
        for pid, _ in sorted(counter.items(), key=lambda x: (-x[1], x[0])):
            pid_str = str(pid).strip()
            if pid_str in active_products and pid_str not in exclude_ids and pid_str not in result:
                p_prod = active_products[pid_str]
                p_cat = str(p_prod.get("category") or "").strip().lower()
                if p_cat == norm_target_cat and _passes_price_filter(p_prod):
                    result.append(pid_str)
                    if len(result) >= needed:
                        return result

        # Remaining active products in that category
        for pid in sorted(active_products.keys()):
            pid_str = str(pid).strip()
            if pid_str not in exclude_ids and pid_str not in result:
                p_prod = active_products[pid_str]
                p_cat = str(p_prod.get("category") or "").strip().lower()
                if p_cat == norm_target_cat and _passes_price_filter(p_prod):
                    result.append(pid_str)
                    if len(result) >= needed:
                        return result

    # 2. If same_category is False (or target has no category), allow other categories
    if not same_category or not norm_target_cat:
        for pid, _ in sorted(counter.items(), key=lambda x: (-x[1], x[0])):
            pid_str = str(pid).strip()
            if pid_str in active_products and pid_str not in exclude_ids and pid_str not in result:
                p_prod = active_products[pid_str]
                if _passes_price_filter(p_prod):
                    result.append(pid_str)
                    if len(result) >= needed:
                        return result

        for pid in sorted(active_products.keys()):
            pid_str = str(pid).strip()
            if pid_str not in exclude_ids and pid_str not in result:
                p_prod = active_products[pid_str]
                if _passes_price_filter(p_prod):
                    result.append(pid_str)
                    if len(result) >= needed:
                        return result

    return result


def _generate_similarity_reasons(
    target_product: dict[str, Any],
    candidate_product: dict[str, Any],
    target_specs: dict[str, float],
    candidate_specs: dict[str, float],
    is_fallback_item: bool = False,
) -> list[str]:
    """Generate concise human-readable explanations for product similarity."""
    if is_fallback_item:
        t_cat = target_product.get("category")
        if t_cat:
            return ["Popular in this category"]
        return ["Popular product"]

    reasons: list[str] = []

    # 1. Category match
    t_cat = str(target_product.get("category") or "").strip().lower()
    c_cat = str(candidate_product.get("category") or "").strip().lower()
    if t_cat and c_cat and t_cat == c_cat:
        reasons.append("Same category")

    # 2. Brand match
    t_brand = str(target_product.get("brand") or "").strip().lower()
    c_brand = str(candidate_product.get("brand") or "").strip().lower()
    if t_brand and c_brand and t_brand == c_brand:
        reasons.append("Same brand")

    # 3. Price comparison
    t_price = target_product.get("price")
    c_price = candidate_product.get("price")
    if t_price is not None and c_price is not None:
        try:
            fp_t = float(t_price)
            fp_c = float(c_price)
            if fp_t > 0 and fp_c > 0:
                diff = round(fp_t - fp_c)
                if diff >= 1:
                    reasons.append(f"Lower price by {int(diff):,}")
                elif diff <= -1:
                    reasons.append(f"Higher price by {int(abs(diff)):,}")
                else:
                    reasons.append("Same price")
        except (ValueError, TypeError):
            pass

    # 4. Specifications comparison
    if target_specs and candidate_specs:
        has_ram = "ram_gb" in target_specs and "ram_gb" in candidate_specs
        has_stor = "storage_gb" in target_specs and "storage_gb" in candidate_specs

        if has_ram and has_stor:
            ram_ratio = min(target_specs["ram_gb"], candidate_specs["ram_gb"]) / max(1e-6, max(target_specs["ram_gb"], candidate_specs["ram_gb"]))
            stor_ratio = min(target_specs["storage_gb"], candidate_specs["storage_gb"]) / max(1e-6, max(target_specs["storage_gb"], candidate_specs["storage_gb"]))
            if ram_ratio >= 0.70 and stor_ratio >= 0.70:
                reasons.append("Similar RAM and storage")
            elif ram_ratio >= 0.70:
                reasons.append("Similar RAM")
            elif stor_ratio >= 0.70:
                reasons.append("Similar storage")
        elif has_ram:
            ram_ratio = min(target_specs["ram_gb"], candidate_specs["ram_gb"]) / max(1e-6, max(target_specs["ram_gb"], candidate_specs["ram_gb"]))
            if ram_ratio >= 0.70:
                reasons.append("Similar RAM")
        elif has_stor:
            stor_ratio = min(target_specs["storage_gb"], candidate_specs["storage_gb"]) / max(1e-6, max(target_specs["storage_gb"], candidate_specs["storage_gb"]))
            if stor_ratio >= 0.70:
                reasons.append("Similar storage")
        else:
            # Check other matching specs
            matching_specs = []
            for k in target_specs:
                if k in candidate_specs:
                    v1 = target_specs[k]
                    v2 = candidate_specs[k]
                    if max(v1, v2) > 0 and (min(v1, v2) / max(v1, v2) >= 0.75):
                        disp_name = {
                            "screen_in": "screen size",
                            "battery_mah": "battery",
                            "camera_mp": "camera",
                            "cpu_cores": "CPU",
                            "weight_g": "weight",
                        }.get(k, k.replace("_", " "))
                        matching_specs.append(disp_name)
            if matching_specs:
                reasons.append(f"Similar {matching_specs[0]}")

    # 5. Text / Attributes fallback reason if specs were missing
    if len(reasons) < 2:
        t_desc = str(target_product.get("description") or "").lower()
        c_desc = str(candidate_product.get("description") or "").lower()
        if t_desc and c_desc:
            t_words = set(t_desc.split())
            c_words = set(c_desc.split())
            if len(t_words & c_words) >= 3:
                reasons.append("Similar description")

    if not reasons:
        reasons.append("Similar attributes")

    return reasons


def _build_similar_item(
    rank: int,
    prod_id: str,
    prod_dict: dict[str, Any],
    similarity: float,
    reasons: list[str],
    target_price: float | None,
) -> dict[str, Any]:
    """Helper to build a complete similar item with specs and price diff calculations."""
    c_price = prod_dict.get("price")
    p_diff = None
    p_diff_pct = None
    if c_price is not None and target_price is not None:
        try:
            fp_c = float(c_price)
            fp_t = float(target_price)
            p_diff = round(fp_c - fp_t, 2)
            if fp_t > 0:
                p_diff_pct = round(((fp_c - fp_t) / fp_t) * 100.0, 1)
        except (ValueError, TypeError):
            pass

    return {
        "rank": rank,
        "product_id": prod_id,
        "product_name": prod_dict.get("product_name", prod_id),
        "category": prod_dict.get("category"),
        "brand": prod_dict.get("brand"),
        "price": prod_dict.get("price"),
        "image_url": prod_dict.get("image_url"),
        "similarity": round(similarity, 2),
        "reasons": reasons,
        "specs": format_human_readable_specs(prod_dict),
        "price_diff": p_diff,
        "price_diff_pct": p_diff_pct,
    }


def find_similar_products(
    tenant_id: str,
    product_id: str,
    top_n: int = 4,
    same_category: bool = True,
    max_price_ratio: float = 2.0,
    storage: StorageBackend | None = None,
    config: dict[str, Any] | None = None,
    rec_id: str | None = None,
) -> dict[str, Any]:
    """Find top_n similar products for product_id.

    Returns response dictionary complying with SimilarProductsResponse.
    Never raises 500 on bad/unknown input; falls back gracefully to popular products.
    """
    clean_pid = str(product_id).strip()
    top_n_clamped = max(1, min(20, top_n))
    active_rec_id = str(rec_id).strip() if rec_id and str(rec_id).strip() else secrets.token_hex(8)

    cfg = _get_config(config)
    if storage is None:
        storage = get_storage_backend(cfg)

    # For large catalogues, pass target product category if known for lazy loading
    active_map = get_active_catalog(tenant_id, storage=storage) or {}
    known_target = active_map.get(clean_pid)
    hint_cat = known_target.get("category") if known_target else None

    index = get_similarity_index(tenant_id, storage=storage, config=cfg, category=hint_cat)

    # -------------------------------------------------------------------------
    # Case 1: Check if product exists in active catalogue / index
    # -------------------------------------------------------------------------
    target_product = index.products.get(clean_pid) or known_target

    if target_product is None:
        # Check if product exists in catalog.csv with status="archived"
        cat_path = f"data/catalog/{tenant_id}/catalog.csv"
        is_archived = False
        target_name = clean_pid
        target_cat = None
        target_brand = None
        target_price = None
        target_img = None
        archived_record: dict[str, Any] = {}

        if storage.exists(cat_path):
            try:
                content = storage.read_file(cat_path)
                cdf = pd.read_csv(io.BytesIO(content), dtype={"product_id": str})
                if not cdf.empty and "product_id" in cdf.columns:
                    cdf["product_id"] = cdf["product_id"].astype(str).str.strip()
                    row_matches = cdf[cdf["product_id"] == clean_pid]
                    if not row_matches.empty:
                        target_row = row_matches.iloc[0]
                        target_name = str(target_row.get("product_name") or clean_pid).strip()
                        target_cat = target_row.get("category")
                        target_brand = target_row.get("brand")
                        raw_tp = target_row.get("price")
                        try:
                            target_price = float(raw_tp) if raw_tp is not None and not pd.isna(raw_tp) else None
                        except (ValueError, TypeError):
                            target_price = None
                        target_img = target_row.get("image_url")
                        archived_record = {k: (None if pd.isna(v) else v) for k, v in target_row.to_dict().items()}
                        status_val = str(target_row.get("status") or "").strip().lower()
                        if status_val == "archived":
                            is_archived = True
            except Exception:
                pass

        fallback_reason = "inactive_product" if is_archived else "unknown_product"

        target_obj = {
            "product_id": clean_pid,
            "product_name": target_name,
            "category": target_cat,
            "brand": target_brand,
            "price": target_price,
            "image_url": target_img,
            "specs": format_human_readable_specs(archived_record) if archived_record else {},
        }

        # Popularity fallback
        pop_pids = _get_active_popular_product_ids(
            tenant_id=tenant_id,
            category=str(target_cat) if target_cat else None,
            exclude_ids={clean_pid},
            needed=top_n_clamped,
            active_products=index.products,
            storage=storage,
        )

        similar_items = []
        for rank, pid in enumerate(pop_pids[:top_n_clamped], start=1):
            prod = index.products.get(pid, {})
            similar_items.append(
                _build_similar_item(
                    rank=rank,
                    prod_id=pid,
                    prod_dict=prod,
                    similarity=0.0,
                    reasons=["Popular in this category"] if target_cat else ["Popular product"],
                    target_price=target_price,
                )
            )

        return {
            "tenant_id": tenant_id,
            "product_id": clean_pid,
            "product_name": target_name,
            "similar": similar_items,
            "similar_products": similar_items,
            "fallback": True,
            "reason": fallback_reason,
            "rec_id": active_rec_id,
            "target": target_obj,
        }

    target_name = str(target_product.get("product_name") or clean_pid).strip()
    target_cat = target_product.get("category")
    target_price = target_product.get("price")
    target_brand = target_product.get("brand")
    target_img = target_product.get("image_url")
    target_specs = index.specs_map.get(clean_pid, {})
    target_idx = index.pid_to_idx.get(clean_pid)

    target_obj = {
        "product_id": clean_pid,
        "product_name": target_name,
        "category": target_cat,
        "brand": target_brand,
        "price": target_price,
        "image_url": target_img,
        "specs": format_human_readable_specs(target_product),
    }

    # -------------------------------------------------------------------------
    # Case 2: Product is active, compute similarity
    # -------------------------------------------------------------------------
    norm_target_cat = str(target_cat).strip().lower() if target_cat else None

    # Memory bounding check (> 100k items restricts candidates to same category)
    restrict_to_cat = False
    if len(index.product_ids) > MAX_UNBOUNDED_CATALOG_SIZE and norm_target_cat:
        restrict_to_cat = True

    # Candidate indices
    if (same_category or restrict_to_cat) and norm_target_cat:
        cand_indices = index.category_indices_arr.get(norm_target_cat, np.empty(0, dtype=np.int32))
    else:
        cand_indices = np.arange(len(index.product_ids), dtype=np.int32)

    # Exclude target product index
    if target_idx is not None and len(cand_indices) > 0:
        cand_indices = cand_indices[cand_indices != target_idx]

    filtered_candidates: list[tuple[str, dict[str, Any], float]] = []

    if target_idx is not None and index.matrix.shape[0] > target_idx and len(cand_indices) > 0:
        query_vec = index.matrix[target_idx]
        if query_vec.nnz > 0:
            # Matrix dot product on entire matrix in single C call (< 2ms for 50k items)
            raw_scores = index.matrix.dot(query_vec.T).toarray().ravel()
            cand_scores = raw_scores[cand_indices]

            # Price ratio filter with numpy
            if max_price_ratio > 0 and target_price is not None:
                try:
                    tp = float(target_price)
                    if tp > 0:
                        min_p = tp / max_price_ratio
                        max_p = tp * max_price_ratio
                        c_prices = index.price_arr[cand_indices]
                        price_mask = np.isnan(c_prices) | (c_prices <= 0) | ((c_prices >= min_p) & (c_prices <= max_p))
                        cand_indices = cand_indices[price_mask]
                        cand_scores = cand_scores[price_mask]
                except (ValueError, TypeError):
                    pass

            # Fast top-K selection
            if len(cand_indices) > 0:
                k = min(top_n_clamped, len(cand_indices))
                if len(cand_indices) > k:
                    top_k_local = np.argpartition(cand_scores, -k)[-k:]
                    top_k_sorted = top_k_local[np.argsort(-cand_scores[top_k_local])]
                else:
                    top_k_sorted = np.argsort(-cand_scores)

                for local_i in top_k_sorted:
                    c_idx = int(cand_indices[local_i])
                    c_pid = index.product_ids[c_idx]
                    c_prod = index.products[c_pid]
                    sim_val = float(cand_scores[local_i])
                    clamped_sim = max(0.0, min(1.0, round(sim_val, 4)))
                    filtered_candidates.append((c_pid, c_prod, clamped_sim))

    # Fill results
    similar_items = []
    used_pids: set[str] = {clean_pid}

    for rank, (c_pid, c_prod, sim) in enumerate(filtered_candidates[:top_n_clamped], start=1):
        used_pids.add(c_pid)
        c_specs = index.specs_map.get(c_pid, {})
        reasons = _generate_similarity_reasons(
            target_product=target_product,
            candidate_product=c_prod,
            target_specs=target_specs,
            candidate_specs=c_specs,
            is_fallback_item=False,
        )
        similar_items.append(
            _build_similar_item(
                rank=rank,
                prod_id=c_pid,
                prod_dict=c_prod,
                similarity=sim,
                reasons=reasons,
                target_price=target_price,
            )
        )

    # If fewer than top_n results pass filters, fill from same-category popularity
    is_fallback = False
    fallback_reason = None

    if len(similar_items) == 0:
        is_fallback = True
        fallback_reason = "limited_product_data"

    if len(similar_items) < top_n_clamped:
        needed = top_n_clamped - len(similar_items)
        pop_fill_pids = _get_active_popular_product_ids(
            tenant_id=tenant_id,
            category=str(target_cat) if target_cat else None,
            exclude_ids=used_pids,
            needed=needed,
            active_products=index.products,
            storage=storage,
            same_category=same_category,
            target_price=target_price,
            max_price_ratio=max_price_ratio,
        )
        start_rank = len(similar_items) + 1
        for i, pid in enumerate(pop_fill_pids, start=start_rank):
            prod = index.products.get(pid, {})
            similar_items.append(
                _build_similar_item(
                    rank=i,
                    prod_id=pid,
                    prod_dict=prod,
                    similarity=0.0,
                    reasons=["Popular in this category"] if target_cat else ["Popular product"],
                    target_price=target_price,
                )
            )

    return {
        "tenant_id": tenant_id,
        "product_id": clean_pid,
        "product_name": target_name,
        "similar": similar_items,
        "similar_products": similar_items,
        "fallback": is_fallback,
        "reason": fallback_reason,
        "rec_id": active_rec_id,
        "target": target_obj,
    }
