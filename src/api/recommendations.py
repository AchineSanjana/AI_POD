"""Domain-agnostic recommendations API endpoints.

Driven by CustomerSchema, ProductSchema, and tenant configuration.
"""

import sys
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from src.utils.config import get_tenant_auth_mapping, load_config

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# In-memory tenant model cache: {tenant_id: loaded_model}
MODEL_CACHE: dict[str, Any] = {}


def clear_model_cache() -> None:
    """Clear the in-memory tenant model cache (useful for testing)."""
    MODEL_CACHE.clear()


def resolve_tenant_id(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    tenant_id: str | None = Query(
        None, description="Optional tenant ID fallback if X-API-Key is not set"
    ),
) -> str:
    """Resolve API key to tenant_id server-side from tenants_auth mapping."""
    config = load_config()
    auth_mapping = get_tenant_auth_mapping(config)

    if x_api_key is not None:
        if x_api_key not in auth_mapping:
            raise HTTPException(
                status_code=401, detail=f"Invalid API Key: '{x_api_key}'"
            )
        return auth_mapping[x_api_key]

    # Fallback to query parameter or default for developer UI / local testing
    return tenant_id or "telco_default"


def get_model_for_tenant(tenant_id: str) -> Any:
    """Retrieve tenant model from cache or load lazily from disk."""
    if tenant_id in MODEL_CACHE:
        return MODEL_CACHE[tenant_id]

    model_path = PROJECT_ROOT / "models" / tenant_id / "final_model.joblib"
    if not model_path.exists() and tenant_id == "telco_default":
        legacy_path = PROJECT_ROOT / "models" / "final_model.joblib"
        if legacy_path.exists():
            model_path = legacy_path

    if not model_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No trained model found for tenant '{tenant_id}'. "
                "Run the pipeline for this tenant first."
            ),
        )

    model = joblib.load(model_path)
    MODEL_CACHE[tenant_id] = model
    return model


def load_model(tenant_id: str = "telco_default") -> Any:
    """Backward compatibility wrapper for loading tenant model."""
    return get_model_for_tenant(tenant_id)


def _get_model_tables(tenant_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    model = get_model_for_tenant(tenant_id)

    customers = getattr(model, "customers_", None)
    products = getattr(model, "products_", None)

    if customers is None or products is None:
        proc_dir = PROJECT_ROOT / "data" / "processed" / tenant_id
        if (
            (proc_dir / "customers.csv").exists()
            and (proc_dir / "products.csv").exists()
        ):
            if customers is None:
                customers = pd.read_csv(proc_dir / "customers.csv")
            if products is None:
                products = pd.read_csv(proc_dir / "products.csv")
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
    tenant_id: str = Depends(resolve_tenant_id),
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "recommendations": _recommend_for_customer(tenant_id, customer_id, top_n),
    }


@router.get("/{customer_id}")
def get_recommendations_for_customer(
    customer_id: str,
    top_n: int = Query(5, ge=1, le=50),
    tenant_id: str = Depends(resolve_tenant_id),
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "recommendations": _recommend_for_customer(tenant_id, customer_id, top_n),
    }