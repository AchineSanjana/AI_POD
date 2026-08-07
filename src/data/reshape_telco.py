"""Reshapes the flat Telco dataset into three tables that mirror the shape
a real recommender system (and eventually the company API) will provide:

    customers.csv     -- one row per customer (demographics, tenure, billing)
    products.csv       -- one row per product/service
    interactions.csv   -- one row per (customer_id, product_id) currently subscribed

This turns a churn-prediction dataset into a usable customer x product
interaction matrix for content-based and collaborative-filtering models.
"""

import warnings

import pandas as pd

from src.data.load_telco import load_raw_telco
from src.utils.config import load_config, resolve_path
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Columns that are simple Yes/No product flags
BINARY_SERVICE_COLUMNS = [
    "PhoneService",
    "MultipleLines",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
]

# Values that mean "does not have this product" across the Telco dataset
NEGATIVE_VALUES = {"No", "No internet service", "No phone service"}

CUSTOMER_COLUMNS = [
    "customerID",
    "gender",
    "SeniorCitizen",
    "Partner",
    "Dependents",
    "tenure",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
    "MonthlyCharges",
    "TotalCharges",
    "Churn",
]


def build_products_table() -> pd.DataFrame:
    """Static product catalog derived from the Telco service columns."""
    products = []

    for col in BINARY_SERVICE_COLUMNS:
        products.append(
            {
                "product_id": col,
                "product_name": _humanize(col),
                "category": "Add-on" if col not in ("PhoneService", "MultipleLines") else "Core",
            }
        )

    # InternetService is categorical (DSL / Fiber optic / No) -> two distinct products
    products.append({"product_id": "InternetService_DSL", "product_name": "Internet - DSL", "category": "Core"})
    products.append({"product_id": "InternetService_Fiber", "product_name": "Internet - Fiber Optic", "category": "Core"})

    df = pd.DataFrame(products)
    logger.info(f"Built products table with {len(df)} products")
    return df


def build_customers_table(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = raw_df[[c for c in CUSTOMER_COLUMNS if c in raw_df.columns]].copy()
    df = df.rename(columns={"customerID": "customer_id"})
    logger.info(f"Built customers table with {len(df)} customers")
    return df


def build_interactions_table(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Long-format (customer_id, product_id) rows for every product a
    customer currently subscribes to.
    """
    rows = []

    for _, row in raw_df.iterrows():
        customer_id = row["customerID"]

        for col in BINARY_SERVICE_COLUMNS:
            if col in raw_df.columns and row[col] not in NEGATIVE_VALUES:
                rows.append({"customer_id": customer_id, "product_id": col})

        internet = row.get("InternetService")
        if internet == "DSL":
            rows.append({"customer_id": customer_id, "product_id": "InternetService_DSL"})
        elif internet == "Fiber optic":
            rows.append({"customer_id": customer_id, "product_id": "InternetService_Fiber"})

    df = pd.DataFrame(rows)
    logger.info(f"Built interactions table with {len(df):,} customer-product rows")
    return df


def _humanize(col: str) -> str:
    """PhoneService -> 'Phone Service', StreamingTV -> 'Streaming TV'

    Inserts a space before an uppercase letter that starts a new word,
    while keeping consecutive-uppercase acronyms (e.g. 'TV') together.
    """
    out = []
    for i, ch in enumerate(col):
        prev_is_lower = i > 0 and col[i - 1].islower()
        if ch.isupper() and out and prev_is_lower:
            out.append(" ")
        out.append(ch)
    return "".join(out)


def run(config: dict | None = None) -> dict[str, pd.DataFrame]:
    warnings.warn(
        "reshape_telco.run() is deprecated. "
        "Use TelcoAdapter(...).run() from src.data.adapters.telco_adapter instead. "
        "reshape_telco.py will be removed in a future release.",
        DeprecationWarning,
        stacklevel=2,
    )
    config = config or load_config()
    raw_df = load_raw_telco(config)

    customers = build_customers_table(raw_df)
    products = build_products_table()
    interactions = build_interactions_table(raw_df)

    out_dir = resolve_path(config["paths"]["processed_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    customers.to_csv(out_dir / config["paths"]["customers_out"], index=False)
    products.to_csv(out_dir / config["paths"]["products_out"], index=False)
    interactions.to_csv(out_dir / config["paths"]["interactions_out"], index=False)

    logger.info(f"Wrote customers/products/interactions tables to {out_dir}")
    return {"customers": customers, "products": products, "interactions": interactions}


if __name__ == "__main__":
    run()
