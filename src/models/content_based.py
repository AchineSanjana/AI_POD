# Domain-agnostic content-based recommender driven by CustomerSchema, ProductSchema, and tenant config.
"""Content-based recommender.

Matches customers to products using customer/product feature similarity.
This is the primary approach for cold-start customers (little/no
interaction history), since it doesn't require prior interactions to work.
"""

from numpy.typing import NDArray
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
        self.numeric_columns_: list[str] = []
        self.categorical_columns_: list[str] = []
        self.categorical_feature_columns_: list[str] = []
        self.transformed_feature_columns_: list[str] = []
        self.customers_: pd.DataFrame | None = None

    def fit(
        self,
        customers: pd.DataFrame,
        interactions: pd.DataFrame,
        feature_columns: list[str],
    ) -> "ContentBasedRecommender":
        """Build an average customer-feature profile per product.

        Args:
            customers: customers table indexed by customer_id, with feature
                columns (e.g. ``numeric_feature_1``, ``numeric_feature_2``).
            interactions: long-format (customer_id, product_id) table.
            feature_columns: columns in `customers` to use as similarity
                features. Categorical columns (e.g. ``categorical_feature_1``)
                are one-hot encoded automatically; numeric columns are
                z-score scaled.
        """
        self.feature_columns_ = feature_columns
        self.customers_ = customers.copy()

        feature_frame = customers[feature_columns].copy()
        self.numeric_columns_ = [
            col for col in feature_columns if pd.api.types.is_numeric_dtype(feature_frame[col])
        ]
        self.categorical_columns_ = [
            col for col in feature_columns if col not in self.numeric_columns_
        ]

        numeric_frame = feature_frame[self.numeric_columns_].astype(float)
        if self.numeric_columns_:
            numeric_scaled = pd.DataFrame(
                self.scaler_.fit_transform(numeric_frame),
                columns=self.numeric_columns_,
                index=feature_frame.index,
            )
        else:
            numeric_scaled = pd.DataFrame(index=feature_frame.index)

        if self.categorical_columns_:
            categorical_dummies = pd.get_dummies(
                feature_frame[self.categorical_columns_],
                prefix=self.categorical_columns_,
            )
            self.categorical_feature_columns_ = list(categorical_dummies.columns)
        else:
            categorical_dummies = pd.DataFrame(index=feature_frame.index)
            self.categorical_feature_columns_ = []

        transformed = pd.concat([numeric_scaled, categorical_dummies], axis=1).astype(float)
        self.transformed_feature_columns_ = list(transformed.columns)

        customer_feature_matrix = customers[["customer_id"]].copy().join(transformed)
        merged = interactions.merge(customer_feature_matrix, on="customer_id", how="left")
        profiles = merged.groupby("product_id")[self.transformed_feature_columns_].mean()
        self.product_profiles_ = pd.DataFrame(profiles)
        logger.info(f"Fit content-based profiles for {len(self.product_profiles_)} products")
        return self

    def _transform_customer_features(self, customer_features: pd.Series) -> NDArray:
        """Transform a customer's feature Series into the scaled and one-hot encoded feature vector."""
        if self.feature_columns_ is None:
            raise RuntimeError("Call fit() before transforming customer features.")

        row = pd.DataFrame([customer_features[self.feature_columns_].tolist()], columns=self.feature_columns_)

        numeric_frame = row[self.numeric_columns_].astype(float) if self.numeric_columns_ else pd.DataFrame(index=[0])
        if self.numeric_columns_:
            numeric_scaled = pd.DataFrame(
                self.scaler_.transform(numeric_frame),
                columns=self.numeric_columns_,
            )
        else:
            numeric_scaled = pd.DataFrame(index=[0])

        if self.categorical_columns_:
            categorical_dummies = pd.get_dummies(
                row[self.categorical_columns_],
                prefix=self.categorical_columns_,
            )
            categorical_dummies = categorical_dummies.reindex(
                columns=self.categorical_feature_columns_,
                fill_value=0,
            )
        else:
            categorical_dummies = pd.DataFrame(index=[0])

        transformed = pd.concat([numeric_scaled, categorical_dummies], axis=1).astype(float)
        transformed = transformed.reindex(columns=self.transformed_feature_columns_, fill_value=0)

        return transformed.to_numpy().reshape(1, -1)

    def _compute_cosine_similarities(self, customer_vec: NDArray) -> pd.Series:
        """Compute cosine similarity between customer vector and all product profiles."""
        if self.product_profiles_ is None:
            raise RuntimeError("Call fit() before computing similarities.")
        similarities = cosine_similarity(customer_vec, self.product_profiles_.values)[0]
        return pd.Series(similarities, index=self.product_profiles_.index)

    def _get_customer_features(self, customer_id: str) -> pd.Series | None:
        """Retrieve customer feature Series by customer_id from fitted customer DataFrame."""
        if self.customers_ is None:
            return None
        if "customer_id" in self.customers_.columns:
            matching = self.customers_.loc[self.customers_["customer_id"].astype(str) == str(customer_id)]
            if not matching.empty:
                return matching.iloc[0]
        if customer_id in self.customers_.index:
            return self.customers_.loc[customer_id]
        if str(customer_id) in self.customers_.index:
            return self.customers_.loc[str(customer_id)]
        return None

    def recommend(self, customer_features: pd.Series, top_k: int = 5) -> list[str]:
        """Return top_k product_ids most similar to a given customer's features."""
        if self.product_profiles_ is None:
            raise RuntimeError("Call fit() before recommend().")

        customer_vec = self._transform_customer_features(customer_features)
        sim_series = self._compute_cosine_similarities(customer_vec)
        ranked = sim_series.sort_values(ascending=False)
        return [str(idx) for idx in ranked.head(top_k).index]

    def score_candidates(
        self,
        customer_id: str,
        candidate_product_ids: list[str],
        customer_features: pd.Series | None = None,
    ) -> dict[str, float]:
        """Return content-based (cosine similarity) relevance scores for candidate products.

        Args:
            customer_id: Target customer ID.
            candidate_product_ids: List of product IDs to score.
            customer_features: Optional customer feature Series. If None, looked up
                from fitted customer records.

        Returns:
            Dictionary mapping each candidate product_id to its cosine similarity score.
            Returns 0.0 for unknown customers or unprofiled products.
        """
        if self.product_profiles_ is None:
            raise RuntimeError("Call fit() before score_candidates().")

        if customer_features is None:
            customer_features = self._get_customer_features(customer_id)

        if customer_features is None:
            logger.warning(
                "customer_id %s not found in fitted customers for content-based scoring", customer_id
            )
            return {str(pid): 0.0 for pid in candidate_product_ids}

        customer_vec = self._transform_customer_features(customer_features)
        sim_series = self._compute_cosine_similarities(customer_vec)

        scores: dict[str, float] = {}
        for pid in candidate_product_ids:
            pid_str = str(pid)
            if pid_str in sim_series.index:
                scores[pid_str] = float(sim_series.loc[pid_str])
            elif pid in sim_series.index:
                scores[pid_str] = float(sim_series.loc[pid])
            else:
                scores[pid_str] = 0.0
        return scores
