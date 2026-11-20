"""Feature matrix builder for tenant product catalogue similarity.

Constructs a sparse feature matrix combining:
1. Category (one-hot)
2. Brand (one-hot)
3. Price (log-scale, min-max scaled within category)
4. Numeric specs (parsed from 'specs' column & extra numeric columns, scaled within category)
5. Text (TF-IDF over name + description + tags, bounded vocabulary)
Weighted by configurable weights with sensible defaults (specs & category highest).
Pre-normalized with L2 row norm for instant request-time cosine dot product.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from src.similarity.specs_parser import extract_numeric_specs

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "category": 0.30,
    "specs": 0.35,
    "brand": 0.15,
    "text": 0.15,
    "price": 0.05,
}


class SimilarityIndex:
    """Encapsulates the tenant similarity feature matrix and product lookup tables."""

    def __init__(
        self,
        tenant_id: str,
        product_ids: list[str],
        products_map: dict[str, dict[str, Any]],
        matrix: sp.csr_matrix,
        weights: dict[str, float],
        specs_map: dict[str, dict[str, float]],
    ) -> None:
        self.tenant_id = tenant_id
        self.product_ids = product_ids
        self.pid_to_idx = {pid: idx for idx, pid in enumerate(product_ids)}
        self.products = products_map
        self.matrix = matrix
        self.weights = weights
        self.specs_map = specs_map

        # Category partitions for bounded memory (> 100k products) and quick filtering
        self.category_product_indices: dict[str, list[int]] = {}
        for idx, pid in enumerate(product_ids):
            p = products_map.get(pid, {})
            cat = str(p.get("category") or "").strip().lower()
            if cat:
                if cat not in self.category_product_indices:
                    self.category_product_indices[cat] = []
                self.category_product_indices[cat].append(idx)

        # Pre-computed numpy arrays for blazingly fast vectorized filtering
        self.category_indices_arr: dict[str, np.ndarray] = {
            c: np.array(indices, dtype=np.int32)
            for c, indices in self.category_product_indices.items()
        }
        self.price_arr: np.ndarray = np.array([
            float(products_map[pid]["price"])
            if products_map.get(pid, {}).get("price") is not None
            else np.nan
            for pid in product_ids
        ], dtype=np.float32)


def _get_weights(config: dict[str, Any] | None = None) -> dict[str, float]:
    """Retrieve similarity feature weights from config or use defaults."""
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(config, dict):
        sim_cfg = config.get("similarity", {})
        if isinstance(sim_cfg, dict):
            cfg_w = sim_cfg.get("weights", {})
            if isinstance(cfg_w, dict):
                for k, v in cfg_w.items():
                    if k in weights:
                        try:
                            weights[k] = float(v)
                        except (ValueError, TypeError):
                            pass

    total = sum(weights.values())
    if total > 0:
        return {k: v / total for k, v in weights.items()}
    return DEFAULT_WEIGHTS


def build_similarity_index(
    tenant_id: str,
    products: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> SimilarityIndex:
    """Build a sparse feature matrix and return a SimilarityIndex for a tenant."""
    weights = _get_weights(config)
    n_products = len(products)

    if n_products == 0:
        empty_csr = sp.csr_matrix((0, 1), dtype=np.float32)
        return SimilarityIndex(
            tenant_id=tenant_id,
            product_ids=[],
            products_map={},
            matrix=empty_csr,
            weights=weights,
            specs_map={},
        )

    product_ids: list[str] = []
    products_map: dict[str, dict[str, Any]] = {}
    specs_map: dict[str, dict[str, float]] = {}

    for p in products:
        pid = str(p.get("product_id") or "").strip()
        if not pid:
            continue
        product_ids.append(pid)
        products_map[pid] = p
        specs_map[pid] = extract_numeric_specs(p)

    n_items = len(product_ids)
    if n_items == 0:
        empty_csr = sp.csr_matrix((0, 1), dtype=np.float32)
        return SimilarityIndex(
            tenant_id=tenant_id,
            product_ids=[],
            products_map={},
            matrix=empty_csr,
            weights=weights,
            specs_map={},
        )

    # Pre-organize products by category
    cats_by_pid: dict[str, str] = {}
    pids_by_cat: dict[str, list[str]] = {}
    for pid in product_ids:
        raw_cat = str(products_map[pid].get("category") or "").strip()
        norm_cat = raw_cat.lower() if raw_cat else "__general__"
        cats_by_pid[pid] = norm_cat
        if norm_cat not in pids_by_cat:
            pids_by_cat[norm_cat] = []
        pids_by_cat[norm_cat].append(pid)

    sub_blocks: list[sp.spmatrix] = []

    # -------------------------------------------------------------------------
    # 1. Category Feature Block (One-Hot)
    # -------------------------------------------------------------------------
    cat_weight = weights.get("category", 0.30)
    all_categories = sorted({cats_by_pid[pid] for pid in product_ids if cats_by_pid[pid] != "__general__"})
    cat_to_col = {c: idx for idx, c in enumerate(all_categories)}

    if all_categories and cat_weight > 0:
        cat_rows: list[int] = []
        cat_cols: list[int] = []
        cat_data: list[float] = []
        w_factor = math.sqrt(cat_weight)

        for i, pid in enumerate(product_ids):
            c = cats_by_pid[pid]
            if c in cat_to_col:
                cat_rows.append(i)
                cat_cols.append(cat_to_col[c])
                cat_data.append(w_factor)

        mat_cat = sp.csr_matrix((cat_data, (cat_rows, cat_cols)), shape=(n_items, len(all_categories)), dtype=np.float32)
        sub_blocks.append(mat_cat)

    # -------------------------------------------------------------------------
    # 2. Brand Feature Block (One-Hot)
    # -------------------------------------------------------------------------
    brand_weight = weights.get("brand", 0.15)
    all_brands = sorted({
        str(products_map[pid].get("brand") or "").strip().lower()
        for pid in product_ids
        if str(products_map[pid].get("brand") or "").strip()
    })
    brand_to_col = {b: idx for idx, b in enumerate(all_brands)}

    if all_brands and brand_weight > 0:
        brand_rows: list[int] = []
        brand_cols: list[int] = []
        brand_data: list[float] = []
        w_factor = math.sqrt(brand_weight)

        for i, pid in enumerate(product_ids):
            b = str(products_map[pid].get("brand") or "").strip().lower()
            if b in brand_to_col:
                brand_rows.append(i)
                brand_cols.append(brand_to_col[b])
                brand_data.append(w_factor)

        mat_brand = sp.csr_matrix((brand_data, (brand_rows, brand_cols)), shape=(n_items, len(all_brands)), dtype=np.float32)
        sub_blocks.append(mat_brand)

    # -------------------------------------------------------------------------
    # 3. Price Feature Block (Log scale, min-max scaled within category)
    # -------------------------------------------------------------------------
    price_weight = weights.get("price", 0.05)
    if price_weight > 0:
        # Calculate min & max log-price per category
        cat_price_bounds: dict[str, tuple[float, float]] = {}
        for c, pids in pids_by_cat.items():
            l_prices = []
            for pid in pids:
                p_val = products_map[pid].get("price")
                try:
                    if p_val is not None and float(p_val) > 0:
                        l_prices.append(math.log1p(float(p_val)))
                except (ValueError, TypeError):
                    pass
            if l_prices:
                cat_price_bounds[c] = (min(l_prices), max(l_prices))

        price_rows: list[int] = []
        price_cols: list[int] = []
        price_data: list[float] = []
        # We represent price as complementary 2D vector [s, 1-s] so equal prices have dot product
        # and missing prices contribute [0, 0]
        w_factor = math.sqrt(price_weight / 2.0)

        for i, pid in enumerate(product_ids):
            p_val = products_map[pid].get("price")
            c = cats_by_pid[pid]
            if p_val is not None and c in cat_price_bounds:
                try:
                    fp = float(p_val)
                    if fp > 0:
                        lp = math.log1p(fp)
                        min_lp, max_lp = cat_price_bounds[c]
                        if max_lp > min_lp:
                            s = max(0.0, min(1.0, (lp - min_lp) / (max_lp - min_lp)))
                        else:
                            s = 0.5
                        price_rows.extend([i, i])
                        price_cols.extend([0, 1])
                        price_data.extend([s * w_factor, (1.0 - s) * w_factor])
                except (ValueError, TypeError):
                    pass

        mat_price = sp.csr_matrix((price_data, (price_rows, price_cols)), shape=(n_items, 2), dtype=np.float32)
        sub_blocks.append(mat_price)

    # -------------------------------------------------------------------------
    # 4. Numeric Specs Block (Min-max scaled WITHIN each category)
    # -------------------------------------------------------------------------
    specs_weight = weights.get("specs", 0.35)
    if specs_weight > 0:
        # Collect distinct specs per category and their min/max values
        # Column identifier is f"{cat}__{spec}" so phone RAM is NEVER compared with laptop RAM!
        cat_spec_bounds: dict[tuple[str, str], tuple[float, float]] = {}
        for c, pids in pids_by_cat.items():
            spec_vals: dict[str, list[float]] = {}
            for pid in pids:
                p_specs = specs_map.get(pid, {})
                for k, v in p_specs.items():
                    if k not in spec_vals:
                        spec_vals[k] = []
                    spec_vals[k].append(v)
            for k, vals in spec_vals.items():
                if vals:
                    cat_spec_bounds[(c, k)] = (min(vals), max(vals))

        all_spec_cols = sorted(cat_spec_bounds.keys())
        spec_col_indices = {key: idx * 2 for idx, key in enumerate(all_spec_cols)}
        n_spec_dims = len(all_spec_cols) * 2

        if n_spec_dims > 0:
            spec_rows: list[int] = []
            spec_cols: list[int] = []
            spec_data: list[float] = []
            w_factor = math.sqrt(specs_weight / 2.0)

            for i, pid in enumerate(product_ids):
                c = cats_by_pid[pid]
                p_specs = specs_map.get(pid, {})
                for k, val in p_specs.items():
                    key = (c, k)
                    if key in cat_spec_bounds and key in spec_col_indices:
                        min_v, max_v = cat_spec_bounds[key]
                        if max_v > min_v:
                            s = max(0.0, min(1.0, (val - min_v) / (max_v - min_v)))
                        else:
                            s = 0.5
                        base_c = spec_col_indices[key]
                        spec_rows.extend([i, i])
                        spec_cols.extend([base_c, base_c + 1])
                        spec_data.extend([s * w_factor, (1.0 - s) * w_factor])

            mat_specs = sp.csr_matrix((spec_data, (spec_rows, spec_cols)), shape=(n_items, n_spec_dims), dtype=np.float32)
            sub_blocks.append(mat_specs)

    # -------------------------------------------------------------------------
    # 5. Light Text Signal (TF-IDF bounded vocabulary)
    # -------------------------------------------------------------------------
    text_weight = weights.get("text", 0.15)
    if text_weight > 0:
        corpus = []
        for pid in product_ids:
            p = products_map[pid]
            name = str(p.get("product_name") or p.get("title") or "")
            desc = str(p.get("description") or "")
            tags = str(p.get("tags") or "")
            combined = f"{name} {desc} {tags}".strip()
            corpus.append(combined if combined else "empty_text")

        tfidf = TfidfVectorizer(max_features=2000, stop_words="english", sublinear_tf=True)
        try:
            mat_text = tfidf.fit_transform(corpus).astype(np.float32)
            # Multiply text matrix by sqrt(text_weight)
            mat_text = mat_text.multiply(math.sqrt(text_weight))
            sub_blocks.append(mat_text)
        except ValueError:
            # Empty corpus or vocabulary
            pass

    # Assemble full sparse feature matrix
    if sub_blocks:
        full_mat = sp.hstack(sub_blocks, format="csr", dtype=np.float32)
    else:
        full_mat = sp.csr_matrix((n_items, 1), dtype=np.float32)

    # Pre-normalize rows with L2 norm so dot product is exact cosine similarity!
    full_mat = normalize(full_mat, norm="l2", axis=1, copy=False)

    return SimilarityIndex(
        tenant_id=tenant_id,
        product_ids=product_ids,
        products_map=products_map,
        matrix=full_mat,
        weights=weights,
        specs_map=specs_map,
    )
