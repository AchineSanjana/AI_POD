"""Utilities for creating offline train/test splits for recommender systems.

Each customer's interactions are partitioned into a training set and a held-out
set of interactions. This enables honest offline evaluation of ranking metrics
such as precision@k, recall@k, and NDCG@k.
"""

from __future__ import annotations

import pandas as pd


def create_train_test_split(
    interactions: pd.DataFrame,
    max_test_items_per_customer: int = 2,
    random_state: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split customer-product interactions into train and held-out test sets.

    For each customer, up to ``max_test_items_per_customer`` interactions are
    held out as test items, while the remaining interactions are kept for
    training. Customers with a single interaction contribute only to the test
    set, since there is no training signal left to preserve.
    """
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
