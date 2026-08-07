"""Regression test: schema-driven ranking model must produce identical recommend()
output to the pre-refactor hardcoded implementation.

Design
------
Rather than checking out a git revision, the pre-Step-3.1 logic is embedded
directly as ``_OldStyleRankingRecommender`` — a subclass that overrides the
three methods that changed (``_resolve_specs``, ``_prepare_data``,
``_build_candidate_row``) with the verbatim pre-refactor code.

Both models are trained on the SAME small fixture dataset with the SAME
XGBoost hyperparameters and random seed.  Because:

  1. The feature column names produced by both implementations are identical
     (verified by ``test_ranking_model_compat.py``).
  2. The column INSERT ORDER is identical (old code hardcodes the order; new
     code iterates specs in the same order via explicit ``customer_specs`` /
     ``product_specs`` with matching ``allowed_values`` order).
  3. XGBoost is deterministic given the same data, column order, and
     ``random_state``.

... the trained models are bitwise-equivalent and ``recommend()`` must return
an identical list for every customer.
"""

from __future__ import annotations

import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from src.core.schema import FeatureSpec
# pyrefly: ignore [missing-import]
from src.models.ranking_model import LearnedRankingRecommender

# ---------------------------------------------------------------------------
# Fixture dataset
# ---------------------------------------------------------------------------

_CUSTOMERS = pd.DataFrame([
    {"customer_id": "c1", "tenure": 12,  "MonthlyCharges": 70.0, "SeniorCitizen": 0, "Contract": "Month-to-month"},
    {"customer_id": "c2", "tenure": 24,  "MonthlyCharges": 90.0, "SeniorCitizen": 0, "Contract": "One year"},
    {"customer_id": "c3", "tenure": 48,  "MonthlyCharges": 55.0, "SeniorCitizen": 1, "Contract": "Two year"},
    {"customer_id": "c4", "tenure":  6,  "MonthlyCharges": 80.0, "SeniorCitizen": 0, "Contract": "Month-to-month"},
])

_PRODUCTS = pd.DataFrame([
    {"product_id": "p1", "category": "Core"},
    {"product_id": "p2", "category": "Core"},
    {"product_id": "p3", "category": "Add-on"},
    {"product_id": "p4", "category": "Add-on"},
])

_INTERACTIONS = pd.DataFrame([
    {"customer_id": "c1", "product_id": "p1"},
    {"customer_id": "c1", "product_id": "p3"},
    {"customer_id": "c2", "product_id": "p2"},
    {"customer_id": "c3", "product_id": "p1"},
    {"customer_id": "c3", "product_id": "p2"},
    {"customer_id": "c4", "product_id": "p4"},
])

_ALL_CUSTOMER_IDS: list[str] = list(_CUSTOMERS["customer_id"])

# ---------------------------------------------------------------------------
# Explicit specs — allowed_values order MUST match the old hardcoded order
# so XGBoost trains on an identical column sequence in both models.
# ---------------------------------------------------------------------------

_CUSTOMER_SPECS: list[FeatureSpec] = [
    FeatureSpec(name="tenure",          dtype="numeric"),
    FeatureSpec(name="MonthlyCharges",  dtype="numeric"),
    FeatureSpec(name="SeniorCitizen",   dtype="numeric"),
    FeatureSpec(
        name="Contract",
        dtype="categorical",
        encoding="one_hot",
        # Order matches the old hardcoded expansion:
        # customer_contract_month_to_month → customer_contract_one_year → customer_contract_two_year
        allowed_values=["Month-to-month", "One year", "Two year"],
    ),
]

_PRODUCT_SPECS: list[FeatureSpec] = [
    FeatureSpec(
        name="category",
        dtype="categorical",
        encoding="one_hot",
        # Order matches the old hardcoded expansion:
        # product_category_core → product_category_add_on
        allowed_values=["Core", "Add-on"],
    ),
]

# ---------------------------------------------------------------------------
# Pre-refactor reference implementation (Step 3.1, before the schema refactor)
# ---------------------------------------------------------------------------


class _OldStyleRankingRecommender(LearnedRankingRecommender):
    """Verbatim pre-refactor logic, embedded inline for comparison.

    Only the three methods changed in Step 3.1 are overridden; the
    fit/recommend/training-frame scaffolding is shared with the new code.
    """

    def _resolve_specs(self) -> None:
        # Pre-refactor: no spec resolution step existed.
        pass

    def _prepare_data(self) -> None:  # type: ignore[override]
        """Original hardcoded dtype coercion."""
        if "customer_id" not in self.customers_.columns:  # type: ignore[union-attr]
            raise ValueError("customers must contain customer_id")
        if "product_id" not in self.products_.columns:  # type: ignore[union-attr]
            raise ValueError("products must contain product_id")

        self.customers_ = self.customers_.copy()  # type: ignore[union-attr]
        self.interactions_ = self.interactions_.copy()  # type: ignore[union-attr]
        self.products_ = self.products_.copy()  # type: ignore[union-attr]

        for column in ["tenure", "MonthlyCharges", "SeniorCitizen"]:
            if column in self.customers_.columns:
                self.customers_[column] = pd.to_numeric(
                    self.customers_[column], errors="coerce"
                )

        self.customers_["Contract"] = (
            self.customers_["Contract"].astype("string")
            if "Contract" in self.customers_.columns
            else None
        )
        self.products_["category"] = (
            self.products_["category"].astype("string")
            if "category" in self.products_.columns
            else None
        )

    def _build_candidate_row(  # type: ignore[override]
        self,
        customer_row: pd.Series,
        product_row: pd.Series,
        target: bool | None = None,
    ) -> dict[str, object]:
        """Original hardcoded one-hot expansion."""
        row: dict[str, object] = {}

        for column in ["tenure", "MonthlyCharges", "SeniorCitizen"]:
            if column in customer_row.index:
                row[f"customer_{column}"] = customer_row[column]

        if "Contract" in customer_row.index:
            row["customer_contract_month_to_month"] = int(
                customer_row["Contract"] == "Month-to-month"
            )
            row["customer_contract_one_year"] = int(
                customer_row["Contract"] == "One year"
            )
            row["customer_contract_two_year"] = int(
                customer_row["Contract"] == "Two year"
            )

        if "category" in product_row.index:
            row["product_category_core"]   = int(product_row["category"] == "Core")
            row["product_category_add_on"] = int(product_row["category"] == "Add-on")

        if "product_id" in product_row.index:
            row["product_id"] = product_row["product_id"]
        if "customer_id" in customer_row.index:
            row["customer_id"] = customer_row["customer_id"]

        if target is not None:
            row["target"] = int(target)

        return row


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIT_KWARGS = dict(n_estimators=10, max_depth=2)


@pytest.fixture(scope="module")
def old_model() -> _OldStyleRankingRecommender:
    return _OldStyleRankingRecommender(**_FIT_KWARGS).fit(
        _CUSTOMERS.copy(), _INTERACTIONS.copy(), _PRODUCTS.copy()
    )


@pytest.fixture(scope="module")
def new_model() -> LearnedRankingRecommender:
    return LearnedRankingRecommender(
        **_FIT_KWARGS,
        customer_specs=_CUSTOMER_SPECS,
        product_specs=_PRODUCT_SPECS,
    ).fit(
        _CUSTOMERS.copy(), _INTERACTIONS.copy(), _PRODUCTS.copy()
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFeatureLayerEquivalence:
    """Verify that both models produce the SAME internal feature representation."""

    def test_feature_columns_identical(
        self,
        old_model: _OldStyleRankingRecommender,
        new_model: LearnedRankingRecommender,
    ) -> None:
        """The ordered list of feature column names must be bit-for-bit identical.

        This is the prerequisite for deterministic XGBoost equivalence — the
        same feature in a different column position would produce a different
        tree structure and different predictions.
        """
        assert old_model.feature_columns_ == new_model.feature_columns_, (
            "Feature column mismatch between old and new model.\n"
            f"  old: {old_model.feature_columns_}\n"
            f"  new: {new_model.feature_columns_}"
        )

    def test_expected_feature_column_names(
        self,
        old_model: _OldStyleRankingRecommender,
    ) -> None:
        """Pin the exact column names the old code produced (regression anchor)."""
        expected = [
            "customer_tenure",
            "customer_MonthlyCharges",
            "customer_SeniorCitizen",
            "customer_contract_month_to_month",
            "customer_contract_one_year",
            "customer_contract_two_year",
            "product_category_core",
            "product_category_add_on",
        ]
        # feature_columns_ includes product_id / customer_id which are then
        # dropped before training; filter to model-input columns only.
        model_input_cols = [
            c for c in old_model.feature_columns_
            if c not in ("product_id", "customer_id")
        ]
        assert model_input_cols == expected


class TestRecommendOutputEquivalence:
    """Core regression: recommend() must return identical results."""

    @pytest.mark.parametrize("customer_id", _ALL_CUSTOMER_IDS)
    def test_recommend_identical_for_each_customer(
        self,
        customer_id: str,
        old_model: _OldStyleRankingRecommender,
        new_model: LearnedRankingRecommender,
    ) -> None:
        """Both models must return the same ordered product list."""
        top_k = len(_PRODUCTS)  # ask for all products so no ties cause divergence
        old_recs = old_model.recommend(customer_id, top_k=top_k)
        new_recs = new_model.recommend(customer_id, top_k=top_k)

        assert old_recs == new_recs, (
            f"Recommendation mismatch for customer {customer_id!r}.\n"
            f"  pre-refactor:  {old_recs}\n"
            f"  post-refactor: {new_recs}\n"
            "The refactor changed model behaviour — feature construction is not equivalent."
        )

    def test_unknown_customer_returns_empty_for_both(
        self,
        old_model: _OldStyleRankingRecommender,
        new_model: LearnedRankingRecommender,
    ) -> None:
        assert old_model.recommend("unknown-id") == []
        assert new_model.recommend("unknown-id") == []

    def test_recommend_only_unseen_products(
        self,
        old_model: _OldStyleRankingRecommender,
        new_model: LearnedRankingRecommender,
    ) -> None:
        """Neither model should recommend products the customer already has."""
        for customer_id in _ALL_CUSTOMER_IDS:
            known = set(
                _INTERACTIONS.loc[
                    _INTERACTIONS["customer_id"] == customer_id, "product_id"
                ]
            )
            for model, label in [(old_model, "old"), (new_model, "new")]:
                recs = set(model.recommend(customer_id, top_k=len(_PRODUCTS)))
                overlap = recs & known
                assert not overlap, (
                    f"[{label}] Recommended already-known products for {customer_id!r}: "
                    f"{overlap}"
                )
