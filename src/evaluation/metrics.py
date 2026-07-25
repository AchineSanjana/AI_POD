"""Offline ranking metrics for evaluating recommendations against held-out
interaction data: precision@k, recall@k, and NDCG@k.
"""

import math


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
    recommended: list[str], relevant: set[str], k: int = 5
) -> dict[str, float]:
    """Convenience wrapper returning all three metrics at once."""
    return {
        f"precision@{k}": precision_at_k(recommended, relevant, k),
        f"recall@{k}": recall_at_k(recommended, relevant, k),
        f"ndcg@{k}": ndcg_at_k(recommended, relevant, k),
    }
