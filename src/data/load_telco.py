"""Loads and cleans the raw Telco Customer Churn CSV.

Download the dataset from Kaggle and place it at:
    data/raw/telco_customer_churn.csv

Source: https://www.kaggle.com/datasets/mosapabdelghany/telcom-customer-churn-dataset
"""

import warnings

import pandas as pd

from src.utils.config import load_config, resolve_path
from src.utils.logger import get_logger

logger = get_logger(__name__)


def load_raw_telco(config: dict | None = None) -> pd.DataFrame:
    """Load the raw Telco CSV and apply light, non-destructive cleaning."""
    config = config or load_config()
    raw_path = (
        resolve_path(config["paths"]["raw_dir"])
        / config["paths"]["telco_raw_file"]
    )

    if not raw_path.exists():
        raise FileNotFoundError(
            f"Expected raw Telco data at {raw_path}.\n"
            "Download it from Kaggle and place it there — see README.md > Setup."
        )

    logger.info(f"Loading raw Telco data from {raw_path}")
    df = pd.read_csv(raw_path, dtype={"customerID": str})

    # TotalCharges is sometimes read as object due to blank strings for new customers
    if "TotalCharges" in df.columns:
        df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce")
        n_missing = df["TotalCharges"].isna().sum()
        if n_missing:
            logger.warning(
                f"{n_missing} rows had non-numeric TotalCharges "
                "(commonly brand-new customers) — coerced to NaN, fill later as needed."
            )

    df.columns = [c.strip() for c in df.columns]
    logger.info(f"Loaded {len(df):,} customer rows, {len(df.columns)} columns")
    return df


if __name__ == "__main__":
    warnings.warn(
        "Running load_telco.py directly is deprecated. "
        "Use TelcoAdapter(...).load_raw() from src.data.adapters.telco_adapter instead.",
        DeprecationWarning,
        stacklevel=1,
    )
    frame = load_raw_telco()
    print(frame.head())
