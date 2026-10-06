"""Domain-agnostic recommendations API endpoints.

Driven by CustomerSchema, ProductSchema, and tenant configuration.
"""

from collections import Counter
import io
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth import get_current_tenant
from src.api.rate_limiter import check_rate_limit
from src.api.schemas import RecommendationItem, RecommendationRequest, RecommendationsResponse
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import get_tenant_auth_mapping, get_tenant_config, load_config, resolve_path
from src.utils.persistence import load_model as persistence_load_model

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/recommendations",
    tags=["recommendations"],
    dependencies=[Depends(check_rate_limit(scope="recommendations"))],
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# In-memory tenant model cache: {tenant_id: loaded_model}
MODEL_CACHE: dict[str, Any] = {}


def clear_model_cache() -> None:
    """Clear the in-memory tenant model cache (useful for testing)."""
    MODEL_CACHE.clear()


# Alias for backward compatibility
resolve_tenant_id = get_current_tenant


def get_model_for_tenant(
    tenant_id: str, storage: StorageBackend | None = None
) -> Any:
    """Retrieve tenant model from cache or load lazily from storage backend."""
    if tenant_id in MODEL_CACHE:
        return MODEL_CACHE[tenant_id]

    if storage is None:
        config = load_config()
        storage = get_storage_backend(config)

    model_path = f"models/{tenant_id}/final_model.joblib"
    if not storage.exists(model_path) and tenant_id == "telco_default":
        legacy_path = "models/final_model.joblib"
        if storage.exists(legacy_path):
            model_path = legacy_path

    if not storage.exists(model_path):
        raise HTTPException(
            status_code=404,
            detail=(
                f"No trained model found for tenant '{tenant_id}'. "
                "Run the pipeline for this tenant first."
            ),
        )

    model = persistence_load_model(model_path, storage=storage)
    MODEL_CACHE[tenant_id] = model
    return model


def load_model(tenant_id: str = "telco_default") -> Any:
    """Backward compatibility wrapper for loading tenant model."""
    return get_model_for_tenant(tenant_id)


def _get_model_tables(
    tenant_id: str, storage: StorageBackend | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if storage is None:
        config = load_config()
        storage = get_storage_backend(config)

    model = get_model_for_tenant(tenant_id, storage=storage)

    customers = getattr(model, "customers_", None)
    products = getattr(model, "products_", None)

    if customers is None or products is None:
        cust_path = f"data/processed/{tenant_id}/customers.csv"
        prod_path = f"data/processed/{tenant_id}/products.csv"
        if storage.exists(cust_path) and storage.exists(prod_path):
            if customers is None:
                customers = pd.read_csv(io.BytesIO(storage.read_file(cust_path)))
            if products is None:
                products = pd.read_csv(io.BytesIO(storage.read_file(prod_path)))
        else:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Trained model for tenant '{tenant_id}' is missing "
                    "embedded customer/product tables"
                ),
            )

    if "customerID" in customers.columns:
        customers = customers.rename(columns={"customerID": "customer_id"})

    return customers.copy(), products.copy()


def is_tenant_trained(tenant_id: str, storage: StorageBackend | None = None) -> bool:
    """Return True if a trained model exists for the given tenant."""
    if tenant_id in MODEL_CACHE:
        return True
    if storage is None:
        config = load_config()
        storage = get_storage_backend(config)

    model_path = f"models/{tenant_id}/final_model.joblib"
    if storage.exists(model_path):
        return True
    if tenant_id == "telco_default" and storage.exists("models/final_model.joblib"):
        return True
    return False


def _get_fallback_recommendations(
    tenant_id: str, top_n: int, storage: StorageBackend | None = None
) -> list[dict[str, Any]]:
    """Generate popularity-based fallback recommendations for an untrained tenant."""
    if storage is None:
        config = load_config()
        storage = get_storage_backend(config)

    counter: Counter[str] = Counter()

    # 1. Check interactions file in processed storage
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
        except Exception as exc:
            logger.warning("Failed reading interactions for fallback (%s): %s", tenant_id, exc)

    # 2. Check in-memory tracking queue stub
    try:
        from src.api.tracking import get_queued_events

        for ev in get_queued_events(tenant_id):
            pid = ev.get("product_id")
            if pid:
                counter[str(pid)] += 1
    except Exception:
        pass

    # 3. Check if tenant has raw/adapter data if counter is still empty
    if not counter:
        try:
            cfg = load_config()
            if tenant_id in cfg.get("tenants", {}):
                from src.data.adapters.generic_config_adapter import GenericConfigAdapter

                t_cfg = get_tenant_config(cfg, tenant_id)
                adapter = GenericConfigAdapter(t_cfg, storage=storage)
                idf = adapter.to_interactions()
                prod_col = "product_id" if "product_id" in idf.columns else None
                if prod_col and prod_col in idf.columns:
                    counter.update(idf[prod_col].dropna().astype(str).tolist())
        except Exception:
            pass

    # 4. Lookup product metadata if available
    product_lookup = None
    prod_path = f"data/processed/{tenant_id}/products.csv"
    if storage.exists(prod_path):
        try:
            p_content = storage.read_file(prod_path)
            pdf = pd.read_csv(io.BytesIO(p_content))
            id_col = "product_id" if "product_id" in pdf.columns else (
                "item_id" if "item_id" in pdf.columns else pdf.columns[0]
            )
            pdf[id_col] = pdf[id_col].astype(str)
            product_lookup = pdf.set_index(id_col)
        except Exception:
            pass

    # Order most common products (break ties by product_id string for deterministic ranking)
    sorted_items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    top_product_ids = [pid for pid, _ in sorted_items[:top_n]]

    recommendations: list[dict[str, Any]] = []
    for rank, pid in enumerate(top_product_ids, start=1):
        p_name = None
        category = None
        if product_lookup is not None and pid in product_lookup.index:
            row = product_lookup.loc[pid]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            for name_field in ("product_name", "title", "Description", "name"):
                if name_field in row and pd.notna(row[name_field]):
                    p_name = str(row[name_field])
                    break
            for cat_field in ("category", "genres", "type"):
                if cat_field in row and pd.notna(row[cat_field]):
                    category = str(row[cat_field])
                    break

        recommendations.append(
            {
                "rank": rank,
                "product_id": pid,
                "product_name": p_name,
                "category": category,
            }
        )

    return recommendations


def _recommend_for_customer(
    tenant_id: str, customer_id: str, top_n: int, storage: StorageBackend | None = None
) -> tuple[list[dict[str, Any]], bool]:
    if storage is None:
        config = load_config()
        storage = get_storage_backend(config)

    # Fallback path for untrained tenants: do not error, return most-frequently-interacted-with products
    if not is_tenant_trained(tenant_id, storage=storage):
        return _get_fallback_recommendations(tenant_id, top_n, storage=storage), True

    try:
        customers, products = _get_model_tables(tenant_id, storage=storage)
    except Exception as exc:
        logger.warning("Could not load model tables for tenant '%s' (%s). Falling back.", tenant_id, exc)
        return _get_fallback_recommendations(tenant_id, top_n, storage=storage), True

    customer_ids = set(customers["customer_id"].astype(str))

    if str(customer_id) not in customer_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Customer '{customer_id}' not found for tenant '{tenant_id}'",
        )

    customer_lookup = customers.set_index("customer_id")
    customer_row = (
        customer_lookup.loc[customer_id]
        if customer_id in customer_lookup.index
        else None
    )

    model = get_model_for_tenant(tenant_id, storage=storage)
    try:
        recommended_ids = model.recommend(customer_id, top_k=top_n)
    except TypeError:
        try:
            recommended_ids = model.recommend(customer_id, customer_row, top_k=top_n)
        except TypeError:
            recommended_ids = model.recommend(customer_row, top_k=top_n)

    if not recommended_ids:
        return [], False

    product_lookup = products.set_index("product_id")
    recommendations: list[dict[str, Any]] = []

    for rank, product_id in enumerate(recommended_ids, start=1):
        product_row = (
            product_lookup.loc[product_id]
            if product_id in product_lookup.index
            else None
        )
        recommendations.append(
            {
                "rank": rank,
                "product_id": product_id,
                "product_name": (
                    None if product_row is None else product_row["product_name"]
                ),
                "category": (
                    None if product_row is None else product_row.get("category")
                ),
            }
        )

    return recommendations, False


@router.get(
    "",
    response_model=RecommendationsResponse,
    summary="Get customer recommendations",
    description="Retrieve personalized top-N product recommendations for a customer. The tenant is resolved from the X-API-Key header.",
)
def get_recommendations(
    customer_id: str = Query(..., description="Customer ID to score"),
    top_n: int = Query(5, ge=1, le=50, description="Number of recommendations to return (1-50)"),
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    """Retrieve personalized product recommendations for a customer."""
    if not customer_id or not customer_id.strip():
        raise HTTPException(status_code=400, detail="customer_id cannot be blank")

    recs, is_fallback = _recommend_for_customer(tenant_id, customer_id.strip(), top_n)
    return {
        "tenant_id": tenant_id,
        "customer_id": customer_id.strip(),
        "recommendations": recs,
        "fallback": is_fallback,
    }


@router.post(
    "",
    response_model=RecommendationsResponse,
    summary="Create customer recommendations",
    description="Retrieve personalized top-N product recommendations for a customer using a JSON request payload.",
)
def create_recommendations(
    payload: RecommendationRequest,
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    """Retrieve recommendations using a JSON request body."""
    if not payload.customer_id or not payload.customer_id.strip():
        raise HTTPException(status_code=400, detail="customer_id cannot be blank")

    recs, is_fallback = _recommend_for_customer(tenant_id, payload.customer_id.strip(), payload.top_n)
    return {
        "tenant_id": tenant_id,
        "customer_id": payload.customer_id.strip(),
        "recommendations": recs,
        "fallback": is_fallback,
    }


@router.get(
    "/{customer_id}",
    response_model=RecommendationsResponse,
    summary="Get recommendations by customer ID path",
    description="Retrieve personalized top-N product recommendations for a specific customer ID passed in the URL path.",
)
def get_recommendations_for_customer(
    customer_id: str,
    top_n: int = Query(5, ge=1, le=50, description="Number of recommendations to return (1-50)"),
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    """Retrieve personalized product recommendations for a customer specified by path."""
    if not customer_id or not customer_id.strip():
        raise HTTPException(status_code=400, detail="customer_id cannot be blank")

    recs, is_fallback = _recommend_for_customer(tenant_id, customer_id.strip(), top_n)
    return {
        "tenant_id": tenant_id,
        "customer_id": customer_id.strip(),
        "recommendations": recs,
        "fallback": is_fallback,
    }