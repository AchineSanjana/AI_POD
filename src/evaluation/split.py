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

    test_rows: list[pd.DataFrame] = []
    train_rows: list[pd.DataFrame] = []

    for group_index, (_, group) in enumerate(interactions.groupby("customer_id", sort=False)):
        group = group.copy()
        if len(group) <= 1:
            test_rows.append(group)
            continue

        n_test = min(max_test_items_per_customer, len(group) - 1)
        sampled = group.sample(
            n=n_test,
            random_state=(random_state + group_index) if random_state is not None else None,
        )
        train_mask = ~group.index.isin(sampled.index)
        train_rows.append(group.loc[train_mask])
        test_rows.append(sampled)

    train_df = pd.concat(train_rows, ignore_index=True) if train_rows else pd.DataFrame(columns=interactions.columns)
    test_df = pd.concat(test_rows, ignore_index=True) if test_rows else pd.DataFrame(columns=interactions.columns)

    return train_df, test_df
