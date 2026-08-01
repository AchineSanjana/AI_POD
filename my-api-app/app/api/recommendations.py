from functools import lru_cache
from pathlib import Path
import sys
from typing import Any

import joblib
import pandas as pd
from fastapi import APIRouter, HTTPException, Query


router = APIRouter(prefix="/recommendations", tags=["recommendations"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_PATH = PROJECT_ROOT / "models" / "final_model.joblib"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@lru_cache(maxsize=1)
def load_model() -> object:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Missing model artifact at {MODEL_PATH}")

    return joblib.load(MODEL_PATH)


def _get_model_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    model = load_model()

    customers = getattr(model, "customers_", None)
    products = getattr(model, "products_", None)
    if customers is None or products is None:
        raise RuntimeError("Saved model is missing embedded customer/product tables")

    if "customerID" in customers.columns:
        customers = customers.rename(columns={"customerID": "customer_id"})

    return customers.copy(), products.copy()


def _recommend_for_customer(customer_id: str, top_n: int) -> list[dict[str, Any]]:
    customers, products = _get_model_tables()
    customer_ids = set(customers["customer_id"])

    if customer_id not in customer_ids:
        raise HTTPException(status_code=404, detail=f"Unknown customer_id: {customer_id}")

    model = load_model()
    recommended_ids = model.recommend(customer_id, top_k=top_n)

    if not recommended_ids:
        return []

    product_lookup = products.set_index("product_id")
    recommendations: list[dict[str, Any]] = []

    for rank, product_id in enumerate(recommended_ids, start=1):
        product_row = product_lookup.loc[product_id] if product_id in product_lookup.index else None
        recommendations.append(
            {
                "rank": rank,
                "product_id": product_id,
                "product_name": None if product_row is None else product_row["product_name"],
                "category": None if product_row is None else product_row.get("category"),
            }
        )

    return recommendations


@router.get("")
def get_recommendations(
    customer_id: str = Query(..., description="Customer ID to score"),
    top_n: int = Query(5, ge=1, le=50),
) -> dict[str, Any]:
    return {
        "customer_id": customer_id,
        "recommendations": _recommend_for_customer(customer_id, top_n),
    }


@router.get("/{customer_id}")
def get_recommendations_for_customer(
    customer_id: str,
    top_n: int = Query(5, ge=1, le=50),
) -> dict[str, Any]:
    return {
        "customer_id": customer_id,
        "recommendations": _recommend_for_customer(customer_id, top_n),
    }