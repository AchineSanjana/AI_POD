"""Collaborative filtering recommender.

"Customers like you subscribe to X." Uses matrix factorization (SVD) over
the customer x product interaction matrix. Requires existing interaction
history, so it complements (rather than replaces) the content-based
recommender for cold-start customers.
"""

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD

from src.utils.logger import get_logger

logger = get_logger(__name__)


class CollaborativeFilteringRecommender:
    def __init__(self, n_factors: int = 20, random_state: int = 42):
        self.n_factors = n_factors
        self.random_state = random_state
        self.model_ = TruncatedSVD(n_components=n_factors, random_state=random_state)
        self.interaction_matrix_: pd.DataFrame | None = None
        self.customer_factors_: np.ndarray | None = None
        self.product_factors_: np.ndarray | None = None

    def fit(self, interactions: pd.DataFrame) -> "CollaborativeFilteringRecommender":
        """Args:
            interactions: long-format (customer_id, product_id) table.
        """
        matrix = (
            interactions.assign(value=1)
            .pivot_table(index="customer_id", columns="product_id", values="value", fill_value=0)
        )
        self.interaction_matrix_ = matrix

        n_products = matrix.shape[1]
        n_components = min(self.n_factors, max(n_products - 1, 1))
        if n_components != self.n_factors:
            logger.warning(
                f"Reducing n_factors to {n_components} (only {n_products} products available)"
            )
        self.model_ = TruncatedSVD(n_components=n_components, random_state=self.random_state)

        self.customer_factors_ = self.model_.fit_transform(matrix.values)
        self.product_factors_ = self.model_.components_.T

        logger.info(
            f"Fit collaborative filtering model: {matrix.shape[0]} customers x "
            f"{matrix.shape[1]} products, {n_components} latent factors"
        )
        return self

    def _compute_scores(self, customer_id: str) -> pd.Series | None:
        """Compute raw SVD dot product scores for all products for a given customer."""
        if self.interaction_matrix_ is None or self.customer_factors_ is None or self.product_factors_ is None:
            raise RuntimeError("Call fit() before scoring.")

        if customer_id in self.interaction_matrix_.index:
            idx = self.interaction_matrix_.index.get_loc(customer_id)
        elif str(customer_id) in self.interaction_matrix_.index:
            idx = self.interaction_matrix_.index.get_loc(str(customer_id))
        else:
            return None

        scores = self.customer_factors_[idx] @ self.product_factors_.T
        return pd.Series(scores, index=self.interaction_matrix_.columns)

    def recommend(self, customer_id: str, top_k: int = 5) -> list[str]:
        if self.interaction_matrix_ is None:
            raise RuntimeError("Call fit() before recommend().")

        score_series = self._compute_scores(customer_id)
        if score_series is None:
            logger.warning(
                f"customer_id {customer_id} has no interaction history "
                "(cold start) -- use ContentBasedRecommender instead."
            )
            return []

        if customer_id in self.interaction_matrix_.index:
            idx = self.interaction_matrix_.index.get_loc(customer_id)
        else:
            idx = self.interaction_matrix_.index.get_loc(str(customer_id))

        already_has = set(
            self.interaction_matrix_.columns[
                self.interaction_matrix_.iloc[idx] > 0
            ]
        )

        ranked = (
            score_series
            .drop(labels=already_has, errors="ignore")
            .sort_values(ascending=False)
        )
        return ranked.head(top_k).index.tolist()

    def score_candidates(
        self, customer_id: str, candidate_product_ids: list[str]
    ) -> dict[str, float]:
        """Return collaborative-filtering (SVD) relevance scores for candidate products.

        Args:
            customer_id: Target customer ID.
            candidate_product_ids: List of product IDs to score.

        Returns:
            Dictionary mapping each candidate product_id to its predicted score.
            For cold-start customers or unknown products, returns 0.0.
        """
        if self.interaction_matrix_ is None:
            raise RuntimeError("Call fit() before score_candidates().")

        score_series = self._compute_scores(customer_id)
        if score_series is None:
            return {str(pid): 0.0 for pid in candidate_product_ids}

        scores: dict[str, float] = {}
        for pid in candidate_product_ids:
            pid_str = str(pid)
            if pid_str in score_series.index:
                scores[pid_str] = float(score_series.loc[pid_str])
            elif pid in score_series.index:
                scores[pid_str] = float(score_series.loc[pid])
            else:
                scores[pid_str] = 0.0
        return scores
