"""Collaborative filtering recommender.

"Customers like you subscribe to X." Uses matrix factorization (SVD) over
the customer x product interaction matrix. Requires existing interaction
history, so it complements (rather than replaces) the content-based
recommender for cold-start customers.
"""

import numpy as np
from numpy.typing import NDArray
import pandas as pd
from sklearn.decomposition import TruncatedSVD

from scipy.sparse import csr_matrix
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CollaborativeFilteringRecommender:
    def __init__(self, n_factors: int = 20, random_state: int = 42):
        self.n_factors = n_factors
        self.random_state = random_state
        self.model_ = TruncatedSVD(n_components=n_factors, random_state=random_state)
        self.customer_index_: pd.Index | None = None
        self.product_index_: pd.Index | None = None
        self.sparse_matrix_: csr_matrix | None = None
        self.customer_factors_: NDArray | None = None
        self.product_factors_: NDArray | None = None

    @property
    def interaction_matrix_(self):
        if self.customer_index_ is None or self.product_index_ is None:
            return None
        class _IndexProxy:
            def __init__(self, c_idx, p_idx):
                self.index = c_idx
                self.columns = p_idx
        return _IndexProxy(self.customer_index_, self.product_index_)

    def fit(self, interactions: pd.DataFrame) -> "CollaborativeFilteringRecommender":
        """Args:
            interactions: long-format (customer_id, product_id) table.
        """
        user_cat = pd.Categorical(interactions["customer_id"].astype(str))
        prod_cat = pd.Categorical(interactions["product_id"].astype(str))

        self.customer_index_ = pd.Index(user_cat.categories)
        self.product_index_ = pd.Index(prod_cat.categories)

        self.sparse_matrix_ = csr_matrix(
            (np.ones(len(interactions), dtype=np.float32), (user_cat.codes, prod_cat.codes)),
            shape=(len(self.customer_index_), len(self.product_index_)),
        )

        n_products = len(self.product_index_)
        n_components = min(self.n_factors, max(n_products - 1, 1))
        if n_components != self.n_factors:
            logger.warning(
                f"Reducing n_factors to {n_components} "
                f"(only {n_products} products available)"
            )
        self.model_ = TruncatedSVD(
            n_components=n_components, random_state=self.random_state
        )

        self.customer_factors_ = self.model_.fit_transform(self.sparse_matrix_)
        assert self.model_.components_ is not None
        self.product_factors_ = self.model_.components_.T

        logger.info(
            f"Fit collaborative filtering model: {self.sparse_matrix_.shape[0]} customers x "
            f"{self.sparse_matrix_.shape[1]} products, {n_components} latent factors"
        )
        return self

    def recommend(self, customer_id: str, top_k: int = 5) -> list[str]:
        if (
            self.customer_index_ is None
            or self.product_index_ is None
            or self.sparse_matrix_ is None
            or self.customer_factors_ is None
            or self.product_factors_ is None
        ):
            raise RuntimeError("Call fit() before recommend().")
        cid_str = str(customer_id)
        if cid_str not in self.customer_index_:
            logger.warning(
                f"customer_id {customer_id} has no interaction history "
                "(cold start) -- use ContentBasedRecommender instead."
            )
            return []

        idx = self.customer_index_.get_loc(cid_str)
        scores = self.customer_factors_[idx] @ self.product_factors_.T

        user_row = self.sparse_matrix_.getrow(idx)
        already_has = self.product_index_[user_row.indices]

        ranked = (
            pd.Series(scores, index=self.product_index_)
            .drop(labels=already_has, errors="ignore")
            .sort_values(ascending=False)
        )
        return [str(x) for x in ranked.head(top_k).index]
