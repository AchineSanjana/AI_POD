# Domain-agnostic hybrid recommender driven by CustomerSchema, ProductSchema, and tenant config.
"""Hybrid recommender.

Blends content-based and collaborative-filtering recommendations so new
customers (cold start) still get sensible suggestions, while customers with
history benefit from collaborative signal. Weighted rank-blend for now;
a learned ranking model (XGBoost/LightGBM) is the natural next step once
this baseline is validated -- see README > Roadmap.
"""

import pandas as pd

from src.models.collaborative_filtering import CollaborativeFilteringRecommender
from src.models.content_based import ContentBasedRecommender
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HybridRecommender:
    def __init__(
        self,
        content_weight: float = 0.5,
        collaborative_weight: float = 0.5,
    ):
        self.content_weight = content_weight
        self.collaborative_weight = collaborative_weight
        self.content_model = ContentBasedRecommender()
        self.cf_model = CollaborativeFilteringRecommender()

    def fit(
        self,
        customers: pd.DataFrame,
        interactions: pd.DataFrame,
        feature_columns: list[str],
    ) -> "HybridRecommender":
        self.content_model.fit(customers, interactions, feature_columns)
        self.cf_model.fit(interactions)
        logger.info("Fit hybrid recommender (content-based + collaborative filtering)")
        return self

    def recommend(
        self,
        customer_id: str,
        customer_features: pd.Series,
        top_k: int = 5,
    ) -> list[str]:
        """Blend rank positions from both models. Falls back to pure
        content-based for customers with no interaction history.
        """
        content_recs = self.content_model.recommend(customer_features, top_k=top_k * 2)
        cf_recs = self.cf_model.recommend(customer_id, top_k=top_k * 2)

        if not cf_recs:
            logger.info(f"No CF history for {customer_id} -- using content-based only")
            return content_recs[:top_k]

        scores: dict[str, float] = {}
        for rank, pid in enumerate(content_recs):
            scores[pid] = scores.get(pid, 0) + self.content_weight * (len(content_recs) - rank)
        for rank, pid in enumerate(cf_recs):
            scores[pid] = scores.get(pid, 0) + self.collaborative_weight * (len(cf_recs) - rank)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [pid for pid, _ in ranked[:top_k]]
