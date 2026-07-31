"""Learned ranking recommender using gradient-boosted trees.

This model trains a binary classifier to predict whether a customer will take a
product, using engineered features from customer, product, and interaction
context. It is intended as a stronger baseline over the hand-built hybrid
ranker once that baseline is validated.
"""

from __future__ import annotations

import pandas as pd
from xgboost import XGBClassifier

from src.utils.logger import get_logger

logger = get_logger(__name__)


class LearnedRankingRecommender:
    def __init__(self, n_estimators: int = 100, max_depth: int = 4) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
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

    def fit(
        self,
        customers: pd.DataFrame,
        interactions: pd.DataFrame,
        products: pd.DataFrame,
    ) -> LearnedRankingRecommender:
        self.customers_ = customers.copy()
        self.interactions_ = interactions.copy()
        self.products_ = products.copy()

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

        if customer_id not in self.customers_["customer_id"].values:
            logger.warning("customer_id %s has no customer profile -- returning empty list", customer_id)
            return []

        customer_row = self.customers_.loc[self.customers_["customer_id"] == customer_id].iloc[0]
        known_products = set(
            self.interactions_.loc[self.interactions_["customer_id"] == customer_id, "product_id"]
        )

        candidate_rows = []
        for _, product in self.products_.iterrows():
            product_id = product["product_id"]
            if product_id in known_products:
                continue
            candidate_rows.append(self._build_candidate_row(customer_row, product))

        if not candidate_rows:
            return []

        candidate_frame = pd.DataFrame(candidate_rows)
        candidate_frame = candidate_frame[self.feature_columns_].drop(columns=["product_id", "customer_id"], errors="ignore")
        scores = self.model_.predict_proba(candidate_frame)[:, 1]
        ranked = pd.Series(scores, index=self.products_.loc[~self.products_["product_id"].isin(known_products), "product_id"])
        return ranked.sort_values(ascending=False).head(top_k).index.tolist()

    def _prepare_data(self) -> None:
        if "customer_id" not in self.customers_.columns:
            raise ValueError("customers must contain customer_id")
        if "product_id" not in self.products_.columns:
            raise ValueError("products must contain product_id")

        self.customers_ = self.customers_.copy()
        self.interactions_ = self.interactions_.copy()
        self.products_ = self.products_.copy()

        for column in ["tenure", "MonthlyCharges", "SeniorCitizen"]:
            if column in self.customers_.columns:
                self.customers_[column] = pd.to_numeric(self.customers_[column], errors="coerce")

        self.customers_["Contract"] = self.customers_["Contract"].astype("string") if "Contract" in self.customers_.columns else None
        self.products_["category"] = self.products_["category"].astype("string") if "category" in self.products_.columns else None

    def _build_training_frame(self) -> pd.DataFrame:
        rows = []
        for _, customer in self.customers_.iterrows():
            customer_id = customer["customer_id"]
            known_products = set(
                self.interactions_.loc[self.interactions_["customer_id"] == customer_id, "product_id"]
            )
            for _, product in self.products_.iterrows():
                rows.append(self._build_candidate_row(customer, product, target=(product["product_id"] in known_products)))

        frame = pd.DataFrame(rows)
        frame = frame.fillna(0)
        return frame

    def _build_candidate_row(self, customer_row: pd.Series, product_row: pd.Series, target: bool | None = None) -> dict[str, object]:
        row: dict[str, object] = {}
        for column in ["tenure", "MonthlyCharges", "SeniorCitizen"]:
            if column in customer_row.index:
                row[f"customer_{column}"] = customer_row[column]
        if "Contract" in customer_row.index:
            row["customer_contract_month_to_month"] = int(customer_row["Contract"] == "Month-to-month")
            row["customer_contract_one_year"] = int(customer_row["Contract"] == "One year")
            row["customer_contract_two_year"] = int(customer_row["Contract"] == "Two year")
        if "category" in product_row.index:
            row["product_category_core"] = int(product_row["category"] == "Core")
            row["product_category_add_on"] = int(product_row["category"] == "Add-on")
        if "product_id" in product_row.index:
            row["product_id"] = product_row["product_id"]
        for column in ["customer_id"]:
            if column in customer_row.index:
                row[column] = customer_row[column]
        if target is not None:
            row["target"] = int(target)
        return row
