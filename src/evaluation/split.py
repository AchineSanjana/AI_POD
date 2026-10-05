"""Utilities for creating offline train/test splits for recommender systems.

Each customer's interactions are partitioned into a training set and a held-out
set of interactions. This enables honest offline evaluation of ranking metrics
such as precision@k, recall@k, and NDCG@k.
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd

from src.utils.config import resolve_path


def get_tenant_interactions_path(
    tenant_id: str = "telco_default",
    data_dir: Path | str | None = None,
) -> Path:
    """Resolve the interactions.csv path for a given tenant_id."""
    if data_dir is not None:
        base = Path(data_dir)
    else:
        base = resolve_path(Path("data") / "processed" / tenant_id)
    return base / "interactions.csv"


def load_tenant_interactions(
    tenant_id: str = "telco_default",
    data_dir: Path | str | None = None,
) -> pd.DataFrame:
    """Load interactions table for a specified tenant."""
    path = get_tenant_interactions_path(tenant_id=tenant_id, data_dir=data_dir)
    if not path.exists():
        legacy_path = resolve_path(Path("data") / "processed" / "interactions.csv")
        if legacy_path.exists() and tenant_id == "telco_default":
            path = legacy_path
        else:
            raise FileNotFoundError(f"Interactions file not found for tenant '{tenant_id}' at {path}")
    return pd.read_csv(path)


def create_train_test_split(
    interactions: pd.DataFrame | None = None,
    max_test_items_per_customer: int = 2,
    random_state: int | None = None,
    tenant_id: str | None = None,
    data_dir: Path | str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split customer-product interactions into train and held-out test sets.

    Args:
        interactions: Optional DataFrame containing long-format customer-product interaction rows.
            If None and tenant_id is provided, loads from data/processed/{tenant_id}/interactions.csv.
        max_test_items_per_customer: Maximum held-out test interactions per customer.
        random_state: Seed for reproducible random sampling.
        tenant_id: Optional tenant identifier to load interactions from data/processed/{tenant_id}/.
        data_dir: Optional base directory override.

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: (train_interactions, test_interactions).
    """
    if interactions is None:
        if tenant_id is None:
            tenant_id = "telco_default"
        interactions = load_tenant_interactions(tenant_id=tenant_id, data_dir=data_dir)

    required_columns = {"customer_id", "product_id"}
    if not required_columns.issubset(interactions.columns):
        missing = sorted(required_columns - set(interactions.columns))
        raise ValueError(f"interactions must contain columns: {missing}")

    if max_test_items_per_customer < 1:
        raise ValueError("max_test_items_per_customer must be at least 1")

    if interactions.empty:
        return interactions.copy(), interactions.iloc[0:0].copy()

    import numpy as np

    df = interactions.copy()
    if random_state is not None:
        rng = np.random.RandomState(random_state)
        rand_vals = rng.rand(len(df))
    else:
        rand_vals = np.random.rand(len(df))

    df["_rand"] = rand_vals
    df["_rank"] = df.groupby("customer_id", sort=False)["_rand"].rank(method="first", ascending=True)
    counts = df.groupby("customer_id", sort=False)["customer_id"].transform("count")

    max_test = np.where(counts <= 1, 1, np.minimum(max_test_items_per_customer, counts - 1))
    is_test = df["_rank"] <= max_test

    test_df = df[is_test].drop(columns=["_rand", "_rank"]).reset_index(drop=True)
    train_df = df[~is_test].drop(columns=["_rand", "_rank"]).reset_index(drop=True)

    return train_df, test_df
