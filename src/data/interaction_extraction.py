"""Shared interaction extraction and product derivation logic driven by InteractionSourceConfig."""

from __future__ import annotations

from typing import Any
import pandas as pd

# pyrefly: ignore [missing-import]
from src.utils.config import (
    InteractionSourceConfig,
    TenantInteractionsConfig,
    TransactionalInteractionsConfig,
)

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


def _extract_config_val(config: Any, key: str, default: Any = None) -> Any:
    """Extract a configuration value from various config shapes (dict, dataclass, etc.)."""
    if isinstance(config, dict):
        if "interactions" in config and isinstance(config["interactions"], dict):
            sub = config["interactions"]
            if key in sub:
                return sub[key]
        if key in config:
            return config[key]
        return default
    if hasattr(config, "transactional") and getattr(config, "transactional") is not None:
        val = getattr(getattr(config, "transactional"), key, None)
        if val is not None:
            return val
    if hasattr(config, key):
        val = getattr(config, key, None)
        if val is not None:
            return val
    if hasattr(config, "interactions") and getattr(config, "interactions") is not None:
        inter = getattr(config, "interactions")
        if hasattr(inter, "transactional") and getattr(inter, "transactional") is not None:
            val = getattr(getattr(inter, "transactional"), key, None)
            if val is not None:
                return val
        if hasattr(inter, key):
            val = getattr(inter, key, None)
            if val is not None:
                return val
    return default


def _format_identifier_series(series: pd.Series) -> pd.Series:
    """Normalize identifier series to clean strings without float '.0' artifacts."""
    def _fmt(val: Any) -> str:
        if pd.isna(val):
            return ""
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        s = str(val).strip()
        if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
            return s[:-2]
        return s

    return series.apply(_fmt)


def build_transactional_interactions(
    raw_df: pd.DataFrame,
    config: Any,
) -> pd.DataFrame:
    """Build canonical long-format interactions table from transactional raw DataFrame.

    Groups rows by (customer_id, product_id) and produces ONE interaction row per
    unique (customer, product) pair the customer has ever purchased, matching the
    existing InteractionSchema shape (customer_id, product_id, and optional weight).

    Args:
        raw_df: Raw DataFrame containing transactional records.
        config: Configuration containing column mappings and cleaning rules. Can be a
            dict, TenantConfig, TenantInteractionsConfig, or TransactionalInteractionsConfig.

    Returns:
        DataFrame strictly conforming to InteractionSchema.
    """
    customer_id_col = _extract_config_val(config, "customer_id_column")
    product_id_col = _extract_config_val(config, "product_id_column")
    quantity_col = _extract_config_val(config, "quantity_column")
    tx_id_col = _extract_config_val(config, "transaction_id_column")
    exclude_prefix = _extract_config_val(config, "exclude_invoice_prefix")

    if not customer_id_col or customer_id_col not in raw_df.columns:
        raise ValueError(
            f"Column '{customer_id_col}' declared as customer_id_column not found in raw data. "
            f"Available columns: {list(raw_df.columns)}"
        )
    if not product_id_col or product_id_col not in raw_df.columns:
        raise ValueError(
            f"Column '{product_id_col}' declared as product_id_column not found in raw data. "
            f"Available columns: {list(raw_df.columns)}"
        )

    if raw_df.empty:
        cols = ["customer_id", "product_id"]
        if quantity_col and quantity_col in raw_df.columns:
            cols.append("weight")
        return pd.DataFrame(columns=cols)

    df = raw_df.copy()

    # 1. Filter rows with missing customer_id or product_id
    cust_s = df[customer_id_col]
    prod_s = df[product_id_col]
    valid_ids = (
        cust_s.notna()
        & prod_s.notna()
        & ~cust_s.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null"])
        & ~prod_s.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null"])
    )
    df = df[valid_ids]

    # 2. Filter missing invoice and cancelled invoices
    effective_tx_col = (
        tx_id_col
        if (tx_id_col and tx_id_col in df.columns)
        else ("InvoiceNo" if "InvoiceNo" in df.columns else None)
    )

    if effective_tx_col is not None:
        tx_s = df[effective_tx_col]
        valid_tx = (
            tx_s.notna()
            & ~tx_s.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null"])
        )
        df = df[valid_tx]

        if exclude_prefix:
            tx_str = df[effective_tx_col].astype(str).str.strip()
            if isinstance(exclude_prefix, (list, tuple, set)):
                prefixes = tuple(str(p).strip() for p in exclude_prefix)
            else:
                prefixes = (str(exclude_prefix).strip(),)
            upper_prefixes = tuple(p.upper() for p in prefixes)
            is_cancelled = tx_str.str.startswith(prefixes) | tx_str.str.upper().str.startswith(upper_prefixes)
            df = df[~is_cancelled]

    if df.empty:
        cols = ["customer_id", "product_id"]
        if quantity_col and quantity_col in raw_df.columns:
            cols.append("weight")
        return pd.DataFrame(columns=cols)

    # 3. Canonicalize customer_id and product_id
    df["customer_id"] = _format_identifier_series(df[customer_id_col])
    df["product_id"] = _format_identifier_series(df[product_id_col])

    # 4. Group rows by (customer_id, product_id)
    if quantity_col and quantity_col in df.columns:
        df["_weight_numeric"] = pd.to_numeric(df[quantity_col], errors="coerce").fillna(1.0)
        grouped = (
            df.groupby(["customer_id", "product_id"], as_index=False)["_weight_numeric"]
            .sum()
            .rename(columns={"_weight_numeric": "weight"})
        )
        grouped["weight"] = grouped["weight"].astype(float)
        result = grouped[["customer_id", "product_id", "weight"]].reset_index(drop=True)
    else:
        result = (
            df[["customer_id", "product_id"]]
            .drop_duplicates()
            .reset_index(drop=True)
        )

    return result


def derive_products_from_transactional(
    raw_df: pd.DataFrame,
    id_column: str,
    name_column: str | None = None,
) -> pd.DataFrame:
    """Derive canonical products catalog DataFrame from transactional raw DataFrame.

    For each distinct product_id, resolves minor description variants by selecting
    the MOST FREQUENT description as its canonical product_name.

    Args:
        raw_df: Raw DataFrame containing transactional records.
        id_column: Name of the product ID column (e.g. 'StockCode').
        name_column: Optional name of the product description column (e.g. 'Description').

    Returns:
        DataFrame with columns 'product_id' and 'product_name'.
    """
    if not id_column or id_column not in raw_df.columns:
        raise ValueError(
            f"Column '{id_column}' declared as products.id_column not found in raw data. "
            f"Available columns: {list(raw_df.columns)}"
        )

    if raw_df.empty:
        return pd.DataFrame(columns=["product_id", "product_name"])

    # 1. Filter out rows with invalid/missing product IDs
    valid_id_mask = (
        raw_df[id_column].notna()
        & ~raw_df[id_column].astype(str).str.strip().str.lower().isin(["", "nan", "none", "null"])
    )
    df = raw_df[valid_id_mask].copy()

    if df.empty:
        return pd.DataFrame(columns=["product_id", "product_name"])

    df["product_id"] = _format_identifier_series(df[id_column])
    df = df[df["product_id"] != ""]

    if df.empty:
        return pd.DataFrame(columns=["product_id", "product_name"])

    # Unique product IDs
    unique_pids = pd.DataFrame({"product_id": sorted(df["product_id"].unique())})

    # 2. Resolve most frequent description per product_id if name_column is available
    if name_column and name_column in df.columns:
        desc_s = df[name_column]
        valid_desc = (
            desc_s.notna()
            & ~desc_s.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null"])
        )
        df_desc = df[valid_desc].copy()
        df_desc["_clean_name"] = df_desc[name_column].astype(str).str.strip()

        if not df_desc.empty:
            counts = (
                df_desc.groupby(["product_id", "_clean_name"])
                .size()
                .reset_index(name="_count")
            )
            counts = counts.sort_values(
                by=["product_id", "_count", "_clean_name"],
                ascending=[True, False, True],
            )
            top_names = counts.drop_duplicates(subset=["product_id"], keep="first")[
                ["product_id", "_clean_name"]
            ].rename(columns={"_clean_name": "product_name"})
            products_df = unique_pids.merge(top_names, on="product_id", how="left")
            products_df["product_name"] = products_df["product_name"].fillna(products_df["product_id"])
        else:
            products_df = unique_pids.copy()
            products_df["product_name"] = products_df["product_id"]
    else:
        products_df = unique_pids.copy()
        products_df["product_name"] = products_df["product_id"]

    return products_df[["product_id", "product_name"]].reset_index(drop=True)
