"""Content-based recommender.

Matches customers to products using customer/product feature similarity.
This is the primary approach for cold-start customers (little/no
interaction history), since it doesn't require prior purchases to work.
"""

import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ContentBasedRecommender:
    """Recommends products based on similarity between customer features
    and the profile of customers who already subscribe to each product.
    """

    def __init__(self):
        self.product_profiles_: pd.DataFrame | None = None
        self.feature_columns_: list[str] | None = None
        self.scaler_ = StandardScaler()

    def fit(
        self,
        customers: pd.DataFrame,
        interactions: pd.DataFrame,
        feature_columns: list[str],
    ) -> "ContentBasedRecommender":
        """Build an average customer-feature profile per product.

        Args:
            customers: customers table indexed by customer_id, with numeric
                feature columns (e.g. tenure, MonthlyCharges).
            interactions: long-format (customer_id, product_id) table.
            feature_columns: numeric columns in `customers` to use as
                similarity features.
        """
        self.feature_columns_ = feature_columns

        merged = interactions.merge(customers, on="customer_id", how="left")
        scaled = customers.copy()
        scaled[feature_columns] = self.scaler_.fit_transform(customers[feature_columns])
        merged_scaled = interactions.merge(scaled, on="customer_id", how="left")

        self.product_profiles_ = (
            merged_scaled.groupby("product_id")[feature_columns].mean()
        )
        logger.info(f"Fit content-based profiles for {len(self.product_profiles_)} products")
        return self

    def recommend(self, customer_features: pd.Series, top_k: int = 5) -> list[str]:
        """Return top_k product_ids most similar to a given customer's features."""
        if self.product_profiles_ is None:
            raise RuntimeError("Call fit() before recommend().")

        customer_vec = self.scaler_.transform(
            customer_features[self.feature_columns_].values.reshape(1, -1)
        )
        similarities = cosine_similarity(customer_vec, self.product_profiles_.values)[0]

        ranked = (
            pd.Series(similarities, index=self.product_profiles_.index)
            .sort_values(ascending=False)
        )
        return ranked.head(top_k).index.tolist()
