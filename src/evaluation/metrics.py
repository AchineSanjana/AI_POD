"""Offline ranking metrics for evaluating recommendations against held-out
interaction data: precision@k, recall@k, and NDCG@k.
"""

from __future__ import annotations

import math
from pathlib import Path
import pandas as pd

from src.utils.config import resolve_path


def precision_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the top-k recommendations that were actually relevant."""
    if k == 0:
        return 0.0
    top_k = recommended[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / k


def recall_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    """Fraction of all relevant items captured in the top-k recommendations."""
    if not relevant:
        return 0.0
    top_k = recommended[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / len(relevant)


def ndcg_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at k.

    Rewards relevant items appearing higher in the ranked list.
    """
    top_k = recommended[:k]

    dcg = sum(
        1.0 / math.log2(rank + 2)  # rank is 0-indexed, +2 avoids log2(1)=0
        for rank, item in enumerate(top_k)
        if item in relevant
    )

    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 2) for rank in range(ideal_hits))

    return dcg / idcg if idcg > 0 else 0.0


def evaluate_all(
    recommended: list[str],
    relevant: set[str],
    k: int = 5,
    tenant_id: str | None = None,
) -> dict[str, float]:
    """Convenience wrapper returning all three metrics at once."""
    return {
        f"precision@{k}": precision_at_k(recommended, relevant, k),
        f"recall@{k}": recall_at_k(recommended, relevant, k),
        f"ndcg@{k}": ndcg_at_k(recommended, relevant, k),
    }


def evaluate_tenant_customer_recommendations(
    recommendations_by_customer: dict[str, list[str]],
    test_interactions: pd.DataFrame | None = None,
    tenant_id: str = "telco_default",
    k: int = 5,
    data_dir: Path | str | None = None,
) -> dict[str, float]:
    """Evaluate customer recommendations against held-out interactions for a tenant."""
    if test_interactions is None:
        if data_dir is not None:
            base = Path(data_dir)
        else:
            base = resolve_path(Path("data") / "processed" / tenant_id)
        test_path = base / "interactions.csv"
        test_interactions = pd.read_csv(test_path)

    metric_rows: list[dict[str, float]] = []
    for customer_id, recommended in recommendations_by_customer.items():
        relevant = set(
            test_interactions.loc[
                test_interactions["customer_id"].astype(str) == str(customer_id), "product_id"
            ].astype(str)
        )
        if not relevant:
            continue
        scores = evaluate_all(recommended, relevant, k=k, tenant_id=tenant_id)
        metric_rows.append(scores)

    if not metric_rows:
        return {f"precision@{k}": 0.0, f"recall@{k}": 0.0, f"ndcg@{k}": 0.0}

    return {
        metric: sum(r[metric] for r in metric_rows) / len(metric_rows)
        for metric in [f"precision@{k}", f"recall@{k}", f"ndcg@{k}"]
    }
