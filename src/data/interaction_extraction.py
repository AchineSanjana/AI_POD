"""Shared interaction extraction and product derivation logic driven by InteractionSourceConfig."""

from __future__ import annotations

import pandas as pd

# pyrefly: ignore [missing-import]
from src.utils.config import InteractionSourceConfig

_INTERNET_SERVICE_COLUMN = "InternetService"

_INTERNET_PRODUCTS = [
    {
        "product_id": "InternetService_DSL",
        "product_name": "Internet - DSL",
        "category": "Core",
    },
    {
        "product_id": "InternetService_Fiber",
        "product_name": "Internet - Fiber Optic",
        "category": "Core",
    },
]


def _humanize(col: str) -> str:
    """``PhoneService`` → ``'Phone Service'``, ``StreamingTV`` → ``'Streaming TV'``."""
    out: list[str] = []
    for i, ch in enumerate(col):
        prev_is_lower = i > 0 and col[i - 1].islower()
        if ch.isupper() and out and prev_is_lower:
            out.append(" ")
        out.append(ch)
    return "".join(out)


def _binary_service_columns(isc: InteractionSourceConfig) -> list[str]:
    """Return service columns excluding ``InternetService``."""
    return [c for c in isc.service_columns if c != _INTERNET_SERVICE_COLUMN]


def derive_products_from_interaction_source(isc: InteractionSourceConfig) -> pd.DataFrame:
    """Derive product catalog DataFrame from an InteractionSourceConfig instance."""
    binary_cols = _binary_service_columns(isc)
    products: list[dict[str, str]] = []

    for col in binary_cols:
        products.append(
            {
                "product_id": col,
                "product_name": _humanize(col),
                "category": (
                    "Core" if col in ("PhoneService", "MultipleLines") else "Add-on"
                ),
            }
        )

    if _INTERNET_SERVICE_COLUMN in isc.service_columns:
        products.extend(_INTERNET_PRODUCTS)
    return pd.DataFrame(products)


def extract_interactions_from_interaction_source(
    raw: pd.DataFrame,
    isc: InteractionSourceConfig,
    id_column: str = "customerID",
) -> pd.DataFrame:
    """Extract long-format (customer_id, product_id) interaction pairs from raw DataFrame."""
    if id_column not in raw.columns:
        raise ValueError(
            f"Column '{id_column}' declared as customers.id_column not found in raw data. "
            f"Available columns: {list(raw.columns)}"
        )

    missing_cols = [col for col in isc.service_columns if col not in raw.columns]
    if missing_cols:
        raise ValueError(
            f"Interaction source column '{missing_cols[0]}' not found in raw data. "
            f"Available columns: {list(raw.columns)}"
        )

    binary_cols = _binary_service_columns(isc)
    negative: set[str] = set(isc.negative_values)

    rows: list[dict[str, str]] = []
    for _, row in raw.iterrows():
        customer_id: str = str(row[id_column])

        # Binary Yes/No columns
        for col in binary_cols:
            if col in raw.columns and row[col] not in negative:
                rows.append({"customer_id": customer_id, "product_id": col})

        # Categorical InternetService → two distinct product IDs
        if _INTERNET_SERVICE_COLUMN in isc.service_columns:
            internet = row.get(_INTERNET_SERVICE_COLUMN)
            if internet == "DSL":
                rows.append(
                    {"customer_id": customer_id, "product_id": "InternetService_DSL"}
                )
            elif internet == "Fiber optic":
                rows.append(
                    {"customer_id": customer_id, "product_id": "InternetService_Fiber"}
                )

    return pd.DataFrame(rows)
