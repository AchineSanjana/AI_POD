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
        self.numeric_columns_: list[str] = []
        self.categorical_columns_: list[str] = []
        self.categorical_feature_columns_: list[str] = []
        self.transformed_feature_columns_: list[str] = []

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
            feature_columns: columns in `customers` to use as similarity
                features. Categorical values such as ``Contract`` are one-hot
                encoded automatically.
        """
        self.feature_columns_ = feature_columns

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
        self.product_profiles_ = merged.groupby("product_id")[self.transformed_feature_columns_].mean()
        logger.info(f"Fit content-based profiles for {len(self.product_profiles_)} products")
        return self

    def recommend(self, customer_features: pd.Series, top_k: int = 5) -> list[str]:
        """Return top_k product_ids most similar to a given customer's features."""
        if self.product_profiles_ is None:
            raise RuntimeError("Call fit() before recommend().")

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

        customer_vec = transformed.to_numpy().reshape(1, -1)
        similarities = cosine_similarity(customer_vec, self.product_profiles_.values)[0]

        ranked = (
            pd.Series(similarities, index=self.product_profiles_.index)
            .sort_values(ascending=False)
        )
        return ranked.head(top_k).index.tolist()
