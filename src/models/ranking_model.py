"""Learned ranking recommender using gradient-boosted trees.

This model trains a binary classifier to predict whether a customer will take a
product, using engineered features from customer, product, and interaction
context. It is intended as a stronger baseline over the hand-built hybrid
ranker once that baseline is validated.

Feature construction is driven entirely by ``FeatureSpec`` definitions rather
than hardcoded column names.  Pass ``customer_specs`` and ``product_specs`` to
``__init__`` (or use :func:`~src.utils.config.build_ranking_feature_specs_from_config`
to derive them from ``config.yaml``) so the model stays decoupled from
field names.

When no specs are provided the model falls back to introspecting the DataFrame
at ``fit()`` time, which preserves backward compatibility with call-sites that
pre-date the schema layer.
"""

from __future__ import annotations

import pandas as pd
from xgboost import XGBClassifier

# pyrefly: ignore [missing-import]
from src.core.encoding import encode_features
# pyrefly: ignore [missing-import]
from src.core.schema import FeatureSpec
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _infer_specs_from_df(df: pd.DataFrame, candidate_cols: list[str]) -> list[FeatureSpec]:
    """Produce FeatureSpec objects by inspecting column dtypes and unique values.

    Used as a fallback when caller supplies no explicit specs so that the model
    stays backward-compatible with call sites that don't yet use the schema layer.

    - Numeric columns → ``FeatureSpec(dtype="numeric")``.
    - Object/string columns → ``FeatureSpec(dtype="categorical", encoding="one_hot",
      allowed_values=<sorted unique non-null values>)``.

    One-hot encoding ensures XGBoost always receives numeric data regardless of
    which encoding strategy is in use.
    """
    specs: list[FeatureSpec] = []
    for col in candidate_cols:
        if col not in df.columns:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            specs.append(FeatureSpec(name=col, dtype="numeric"))
        else:
            # Derive allowed_values from observed non-null unique values so that
            # one-hot columns are consistent across fit/predict.
            unique_vals = sorted(str(v) for v in df[col].dropna().unique())
            specs.append(
                FeatureSpec(
                    name=col,
                    dtype="categorical",
                    encoding="one_hot",
                    allowed_values=unique_vals,
                )
            )
    return specs


def _coerce_dtypes(df: pd.DataFrame, specs: list[FeatureSpec]) -> pd.DataFrame:
    """Return a copy of *df* with columns coerced according to each FeatureSpec.

    - ``dtype="numeric"``      → ``pd.to_numeric(..., errors="coerce")``
    - ``dtype="categorical"``  → ``.astype("string")``

    Columns absent from the DataFrame are silently skipped.
    """
    df = df.copy()
    for spec in specs:
        if spec.name not in df.columns:
            continue
        if spec.dtype == "numeric":
            df[spec.name] = pd.to_numeric(df[spec.name], errors="coerce")
        elif spec.dtype == "categorical":
            df[spec.name] = df[spec.name].astype("string")
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class LearnedRankingRecommender:
    """Gradient-boosted ranking recommender driven by ``FeatureSpec`` definitions.

    Args:
        n_estimators: Number of XGBoost trees.
        max_depth: Maximum tree depth.
        customer_specs: Feature specs for the customer table.  When ``None``
            (default) the model infers minimal specs from the DataFrame at
            ``fit()`` time for backward compatibility.
        product_specs: Feature specs for the product table.  When ``None``
            the model infers minimal specs from the DataFrame at ``fit()`` time.
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 4,
        customer_specs: list[FeatureSpec] | None = None,
        product_specs: list[FeatureSpec] | None = None,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.customer_specs: list[FeatureSpec] | None = customer_specs
        self.product_specs: list[FeatureSpec] | None = product_specs

        self.model_ = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            eval_metric="logloss",
            random_state=42,
        )
        self.customers_: pd.DataFrame | None = None
        self.interactions_: pd.DataFrame | None = None
        self.products_: pd.DataFrame | None = None
        self.feature_columns_: list[str] = []

        # Resolved specs — set during fit() once we have the DataFrames in hand.
        self._customer_specs: list[FeatureSpec] = []
        self._product_specs: list[FeatureSpec] = []

    def fit(
        self,
        customers: pd.DataFrame,
        interactions: pd.DataFrame,
        products: pd.DataFrame,
    ) -> LearnedRankingRecommender:
        self.customers_ = customers.copy()
        self.interactions_ = interactions.copy()
        self.products_ = products.copy()

        self._resolve_specs()
        self._prepare_data()
        training_frame = self._build_training_frame()
        self.feature_columns_ = [c for c in training_frame.columns if c != "target"]

        X = training_frame[self.feature_columns_].drop(columns=["product_id", "customer_id"], errors="ignore")
        y = training_frame["target"]
        self.model_.fit(X, y)
        logger.info("Fit learned ranking model")
        return self

    def recommend(self, customer_id: str, top_k: int = 5) -> list[str]:
        if self.customers_ is None or self.interactions_ is None or self.products_ is None:
            raise RuntimeError("Call fit() before recommend().")

        # Bind to locals so Pyright narrows pd.DataFrame | None → pd.DataFrame.
        # Instance attributes are not narrowed across method calls; locals are.
        customers = self.customers_
        interactions = self.interactions_
        products = self.products_

        if customer_id not in customers["customer_id"].values:
            logger.warning("customer_id %s has no customer profile -- returning empty list", customer_id)
            return []

        customer_row = customers.loc[customers["customer_id"] == customer_id].iloc[0]
        known_products = set(
            interactions.loc[interactions["customer_id"] == customer_id, "product_id"]
        )

        candidate_rows = []
        for _, product in products.iterrows():
            product_id = product["product_id"]
            if product_id in known_products:
                continue
            candidate_rows.append(self._build_candidate_row(customer_row, product))

        if not candidate_rows:
            return []

        candidate_frame = pd.DataFrame(candidate_rows)
        candidate_frame = candidate_frame[self.feature_columns_].drop(columns=["product_id", "customer_id"], errors="ignore")
        scores = self.model_.predict_proba(candidate_frame)[:, 1]
        ranked = pd.Series(scores, index=products.loc[~products["product_id"].isin(known_products), "product_id"])
        return ranked.sort_values(ascending=False).head(top_k).index.tolist()


    # ------------------------------------------------------------------
    # Internal — spec resolution
    # ------------------------------------------------------------------

    def _resolve_specs(self) -> None:
        """Populate ``_customer_specs`` and ``_product_specs`` from constructor
        args or, when absent, by introspecting the fitted DataFrames.

        Called once inside ``fit()`` after the DataFrames are stored.
        """
        non_feature_customer_cols = {"customer_id"}
        non_feature_product_cols = {"product_id", "product_name"}

        if self.customer_specs is not None:
            self._customer_specs = self.customer_specs
        else:
            candidate_cols = [
                c for c in self.customers_.columns  # type: ignore[union-attr]
                if c not in non_feature_customer_cols
            ]
            self._customer_specs = _infer_specs_from_df(self.customers_, candidate_cols)  # type: ignore[arg-type]

        if self.product_specs is not None:
            self._product_specs = self.product_specs
        else:
            candidate_cols = [
                c for c in self.products_.columns  # type: ignore[union-attr]
                if c not in non_feature_product_cols
            ]
            self._product_specs = _infer_specs_from_df(self.products_, candidate_cols)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Internal — data preparation
    # ------------------------------------------------------------------

    def _prepare_data(self) -> None:
        """Validate primary keys and coerce column dtypes via FeatureSpec."""
        if "customer_id" not in self.customers_.columns:  # type: ignore[union-attr]
            raise ValueError("customers must contain customer_id")
        if "product_id" not in self.products_.columns:  # type: ignore[union-attr]
            raise ValueError("products must contain product_id")

        # Coerce dtypes driven by specs — no hardcoded column names.
        self.customers_ = _coerce_dtypes(self.customers_, self._customer_specs)  # type: ignore[arg-type]
        self.products_ = _coerce_dtypes(self.products_, self._product_specs)  # type: ignore[arg-type]
        self.interactions_ = self.interactions_.copy()  # type: ignore[union-attr]

    def _build_training_frame(self) -> pd.DataFrame:
        rows = []
        for _, customer in self.customers_.iterrows():  # type: ignore[union-attr]
            customer_id = customer["customer_id"]
            known_products = set(
                self.interactions_.loc[self.interactions_["customer_id"] == customer_id, "product_id"]  # type: ignore[union-attr]
            )
            for _, product in self.products_.iterrows():  # type: ignore[union-attr]
                rows.append(self._build_candidate_row(customer, product, target=(product["product_id"] in known_products)))

        frame = pd.DataFrame(rows)
        frame = frame.fillna(0)
        return frame

    def _build_candidate_row(
        self,
        customer_row: pd.Series,
        product_row: pd.Series,
        target: bool | None = None,
    ) -> dict[str, object]:
        """Encode one (customer, product) pair into a flat feature dict.

        Feature names and encoding rules come entirely from ``_customer_specs``
        and ``_product_specs`` — no hardcoded column names.
        """
        row: dict[str, object] = {}

        # Customer features — driven by specs, prefixed with "customer_"
        customer_encoded = encode_features(customer_row, self._customer_specs, prefix="customer_")
        row.update(customer_encoded)

        # Product features — driven by specs, prefixed with "product_"
        product_encoded = encode_features(product_row, self._product_specs, prefix="product_")
        row.update(product_encoded)

        # Pass-through primary keys (dropped from X before training/scoring,
        # kept here so feature_columns_ alignment works correctly).
        if "product_id" in product_row.index:
            row["product_id"] = product_row["product_id"]
        if "customer_id" in customer_row.index:
            row["customer_id"] = customer_row["customer_id"]

        if target is not None:
            row["target"] = int(target)

        return row
