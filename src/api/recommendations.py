"""Domain-agnostic recommendations API endpoints.

Driven by CustomerSchema, ProductSchema, and tenant configuration.
"""

import io
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth import get_current_tenant
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import get_tenant_auth_mapping, load_config
from src.utils.persistence import load_model as persistence_load_model

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

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


class RecommendationRequest(BaseModel):
    customer_id: str
    top_n: int = Field(5, ge=1, le=50)
    tenant_id: str | None = Field(
        None,
        description="Ignored. The tenant identity is always derived from the X-API-Key header.",
    )


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


def _recommend_for_customer(
    tenant_id: str, customer_id: str, top_n: int
) -> list[dict[str, Any]]:
    customers, products = _get_model_tables(tenant_id)
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

    model = get_model_for_tenant(tenant_id)
    try:
        recommended_ids = model.recommend(customer_id, top_k=top_n)
    except TypeError:
        try:
            recommended_ids = model.recommend(customer_id, customer_row, top_k=top_n)
        except TypeError:
            recommended_ids = model.recommend(customer_row, top_k=top_n)

    if not recommended_ids:
        return []

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

    return recommendations


@router.get("")
def get_recommendations(
    customer_id: str = Query(..., description="Customer ID to score"),
    top_n: int = Query(5, ge=1, le=50),
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "recommendations": _recommend_for_customer(tenant_id, customer_id, top_n),
    }


@router.post("")
def create_recommendations(
    payload: RecommendationRequest,
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "customer_id": payload.customer_id,
        "recommendations": _recommend_for_customer(tenant_id, payload.customer_id, payload.top_n),
    }


@router.get("/{customer_id}")
def get_recommendations_for_customer(
    customer_id: str,
    top_n: int = Query(5, ge=1, le=50),
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "recommendations": _recommend_for_customer(tenant_id, customer_id, top_n),
    }