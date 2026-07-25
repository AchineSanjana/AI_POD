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

    def recommend(self, customer_id: str, top_k: int = 5) -> list[str]:
        if self.interaction_matrix_ is None:
            raise RuntimeError("Call fit() before recommend().")
        if customer_id not in self.interaction_matrix_.index:
            logger.warning(
                f"customer_id {customer_id} has no interaction history "
                "(cold start) -- use ContentBasedRecommender instead."
            )
            return []

        idx = self.interaction_matrix_.index.get_loc(customer_id)
        scores = self.customer_factors_[idx] @ self.product_factors_.T

        already_has = set(
            self.interaction_matrix_.columns[
                self.interaction_matrix_.iloc[idx] > 0
            ]
        )

        ranked = (
            pd.Series(scores, index=self.interaction_matrix_.columns)
            .drop(labels=already_has, errors="ignore")
            .sort_values(ascending=False)
        )
        return ranked.head(top_k).index.tolist()
