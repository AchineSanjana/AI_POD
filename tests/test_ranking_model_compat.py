"""Compatibility test: schema-driven encoding must reproduce old hardcoded column names.

Purpose
-------
The original ``_build_candidate_row()`` in ``ranking_model.py`` hardcoded both
the column names and the one-hot expansion logic:

    row["customer_contract_month_to_month"] = int(customer_row["Contract"] == "Month-to-month")
    row["customer_contract_one_year"]        = int(customer_row["Contract"] == "One year")
    row["customer_contract_two_year"]        = int(customer_row["Contract"] == "Two year")
    row["product_category_core"]             = int(product_row["category"] == "Core")
    row["product_category_add_on"]           = int(product_row["category"] == "Add-on")

The refactored model delegates this to ``encode_features()`` with a
``FeatureSpec`` list derived from ``config.yaml``.  This test verifies that
the new path produces *identical* column names and values for the same inputs,
preserving compatibility with any artefact that was trained on those column names.

Model-artefact status
---------------------
``models/final_model.joblib`` **requires retraining** before it can be used
with the refactored ``LearnedRankingRecommender``.  There are two independent
reasons:

1. **Pickle incompatibility** — the artefact was serialised with an older
   pandas version (``StringDtype`` ABI mismatch).  ``joblib.load()`` raises
   ``TypeError: StringDtype.__init__() takes from 1 to 2 positional arguments
   but 3 were given`` before it even reaches the model object.  This is
   unrelated to the schema refactor.

2. **Missing attributes** — even if deserialization succeeded, the pickled
   object pre-dates the ``_customer_specs`` / ``_product_specs`` attributes
   introduced by the refactor.  Calling ``recommend()`` on a loaded artefact
   would raise ``AttributeError: 'LearnedRankingRecommender' has no attribute
   '_customer_specs'`` because ``__init__`` is not re-run on unpickling.

Action: run ``python scripts/train_model.py`` to produce a fresh artefact that
is compatible with both the current Python/pandas environment and the refactored
class interface.
"""

from __future__ import annotations

import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from src.core.encoding import encode_features
# pyrefly: ignore [missing-import]
from src.utils.config import build_ranking_feature_specs_from_config, load_config

# ---------------------------------------------------------------------------
# Reference: exact column names produced by the OLD hardcoded implementation
# ---------------------------------------------------------------------------

_OLD_CUSTOMER_COLUMNS: frozenset[str] = frozenset({
    "customer_tenure",
    "customer_MonthlyCharges",
    "customer_SeniorCitizen",
    "customer_contract_month_to_month",
    "customer_contract_one_year",
    "customer_contract_two_year",
})

_OLD_PRODUCT_COLUMNS: frozenset[str] = frozenset({
    "product_category_core",
    "product_category_add_on",
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ranking_specs() -> tuple[list, list]:
    cfg = load_config()
    customer_specs, product_specs = build_ranking_feature_specs_from_config(cfg)
    return customer_specs, product_specs


def _customer_row() -> pd.Series:
    """Synthetic row with every ranking customer feature present."""
    return pd.Series({
        "customer_id": "C001",
        "tenure": 12,
        "MonthlyCharges": 70.0,
        "SeniorCitizen": 0,
        "Contract": "Month-to-month",
    })


def _product_row(category: str = "Core") -> pd.Series:
    return pd.Series({"product_id": "PhoneService", "category": category})


# ---------------------------------------------------------------------------
# Column-name compatibility
# ---------------------------------------------------------------------------


class TestColumnNameCompat:
    """Schema-driven encoding must produce identical column names to the old
    hardcoded implementation."""

    def test_customer_column_names_match_old(self, ranking_specs) -> None:
        customer_specs, _ = ranking_specs
        encoded = encode_features(_customer_row(), customer_specs, prefix="customer_")
        new_cols = frozenset(encoded.keys())
        assert new_cols == _OLD_CUSTOMER_COLUMNS, (
            "Customer column name mismatch between new encoding and old hardcoded names.\n"
            f"  Missing from new encoding: {_OLD_CUSTOMER_COLUMNS - new_cols}\n"
            f"  Extra in new encoding:     {new_cols - _OLD_CUSTOMER_COLUMNS}\n"
            "If this fails, the encode_features() naming scheme diverged from the old "
            "_build_candidate_row() output."
        )

    def test_product_column_names_match_old(self, ranking_specs) -> None:
        _, product_specs = ranking_specs
        encoded = encode_features(_product_row(), product_specs, prefix="product_")
        new_cols = frozenset(encoded.keys())
        assert new_cols == _OLD_PRODUCT_COLUMNS, (
            "Product column name mismatch between new encoding and old hardcoded names.\n"
            f"  Missing from new encoding: {_OLD_PRODUCT_COLUMNS - new_cols}\n"
            f"  Extra in new encoding:     {new_cols - _OLD_PRODUCT_COLUMNS}"
        )


# ---------------------------------------------------------------------------
# Value compatibility
# ---------------------------------------------------------------------------


class TestEncodedValueCompat:
    """Same column names AND same values for each possible categorical input."""

    def test_numeric_customer_values(self, ranking_specs) -> None:
        customer_specs, _ = ranking_specs
        encoded = encode_features(_customer_row(), customer_specs, prefix="customer_")
        assert encoded["customer_tenure"] == 12
        assert encoded["customer_MonthlyCharges"] == 70.0
        assert encoded["customer_SeniorCitizen"] == 0

    @pytest.mark.parametrize("contract_val,active_col", [
        ("Month-to-month", "customer_contract_month_to_month"),
        ("One year",       "customer_contract_one_year"),
        ("Two year",       "customer_contract_two_year"),
    ])
    def test_contract_one_hot_active_column(
        self, contract_val: str, active_col: str, ranking_specs
    ) -> None:
        """Each Contract value activates exactly one column and zeros the rest."""
        customer_specs, _ = ranking_specs
        row = pd.Series({
            "tenure": 0,
            "MonthlyCharges": 0.0,
            "SeniorCitizen": 0,
            "Contract": contract_val,
        })
        encoded = encode_features(row, customer_specs, prefix="customer_")
        contract_cols = {c for c in encoded if c.startswith("customer_contract_")}
        assert active_col in contract_cols, (
            f"Expected column {active_col!r} not found for Contract={contract_val!r}"
        )
        assert encoded[active_col] == 1, (
            f"Column {active_col!r} should be 1 for Contract={contract_val!r}"
        )
        for col in contract_cols - {active_col}:
            assert encoded[col] == 0, (
                f"Column {col!r} should be 0 when Contract={contract_val!r}"
            )

    @pytest.mark.parametrize("category_val,active_col", [
        ("Core",   "product_category_core"),
        ("Add-on", "product_category_add_on"),
    ])
    def test_category_one_hot_active_column(
        self, category_val: str, active_col: str, ranking_specs
    ) -> None:
        """Each category value activates exactly one column and zeros the rest."""
        _, product_specs = ranking_specs
        encoded = encode_features(_product_row(category_val), product_specs, prefix="product_")
        category_cols = {c for c in encoded if c.startswith("product_category_")}
        assert active_col in category_cols
        assert encoded[active_col] == 1
        for col in category_cols - {active_col}:
            assert encoded[col] == 0

    def test_full_row_identical_to_old_hardcoded(self, ranking_specs) -> None:
        """End-to-end: combined customer+product dict must equal old hardcoded output."""
        customer_specs, product_specs = ranking_specs
        customer_row = _customer_row()
        product_row = _product_row("Add-on")

        new_row: dict = {}
        new_row.update(encode_features(customer_row, customer_specs, prefix="customer_"))
        new_row.update(encode_features(product_row, product_specs, prefix="product_"))

        # Old hardcoded _build_candidate_row() would have produced exactly this:
        expected = {
            "customer_tenure": 12,
            "customer_MonthlyCharges": 70.0,
            "customer_SeniorCitizen": 0,
            "customer_contract_month_to_month": 1,
            "customer_contract_one_year": 0,
            "customer_contract_two_year": 0,
            "product_category_core": 0,
            "product_category_add_on": 1,
        }

        assert set(new_row.keys()) == set(expected.keys()), (
            f"Column mismatch:\n"
            f"  Missing: {set(expected) - set(new_row)}\n"
            f"  Extra:   {set(new_row) - set(expected)}"
        )
        for col, val in expected.items():
            assert new_row[col] == val, (
                f"Value mismatch for {col!r}: expected {val!r}, got {new_row[col]!r}"
            )
