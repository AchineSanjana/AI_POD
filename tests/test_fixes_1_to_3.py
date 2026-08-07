"""Tests for fixes 1–3:

1. config.yaml model feature subsets + validation helpers in config.py
2. encode_categorical_features() DataFrame-level utility
3. validate_values() on CustomerSchema, ProductSchema, InteractionSchema
"""

import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from src.core.encoding import encode_categorical_features
# pyrefly: ignore [missing-import]
from src.core.schema import CustomerSchema, FeatureSpec, InteractionSchema, ProductSchema
# pyrefly: ignore [missing-import]
from src.utils.config import (
    build_content_based_feature_specs_from_config,
    build_ranking_feature_specs_from_config,
    get_content_feature_columns,
    load_config,
    validate_model_feature_lists,
)


# ---------------------------------------------------------------------------
# Fix 1 — model feature-subset lists in config.yaml + helpers in config.py
# ---------------------------------------------------------------------------


class TestModelFeatureSubsetsInConfig:
    def test_content_based_features_key_exists(self):
        cfg = load_config()
        assert "features" in cfg["model"]["content_based"]
        assert isinstance(cfg["model"]["content_based"]["features"], list)
        assert len(cfg["model"]["content_based"]["features"]) > 0

    def test_ranking_customer_and_product_features_keys_exist(self):
        cfg = load_config()
        ranking = cfg["model"]["ranking"]
        assert "customer_features" in ranking
        assert "product_features" in ranking
        assert isinstance(ranking["customer_features"], list)
        assert isinstance(ranking["product_features"], list)

    def test_build_content_based_feature_specs_returns_feature_specs(self):
        cfg = load_config()
        specs = build_content_based_feature_specs_from_config(cfg)
        assert specs
        assert all(isinstance(s, FeatureSpec) for s in specs)
        expected_names = set(cfg["model"]["content_based"]["features"])
        assert {s.name for s in specs} == expected_names

    def test_get_content_feature_columns_returns_list_of_strings(self):
        cfg = load_config()
        cols = get_content_feature_columns(cfg)
        assert isinstance(cols, list)
        assert cols == cfg["model"]["content_based"]["features"]

    def test_build_ranking_feature_specs_returns_two_lists(self):
        cfg = load_config()
        customer_specs, product_specs = build_ranking_feature_specs_from_config(cfg)
        assert all(isinstance(s, FeatureSpec) for s in customer_specs)
        assert all(isinstance(s, FeatureSpec) for s in product_specs)
        assert {s.name for s in customer_specs} == set(cfg["model"]["ranking"]["customer_features"])
        assert {s.name for s in product_specs} == set(cfg["model"]["ranking"]["product_features"])

    def test_validate_model_feature_lists_passes_for_valid_config(self):
        cfg = load_config()
        validate_model_feature_lists(cfg)  # must not raise

    def test_validate_model_feature_lists_raises_for_unknown_content_based_feature(self):
        cfg = load_config()
        cfg = {**cfg, "model": {**cfg["model"], "content_based": {**cfg["model"]["content_based"], "features": ["tenure", "NONEXISTENT_COLUMN"]}}}
        with pytest.raises(ValueError, match="NONEXISTENT_COLUMN"):
            validate_model_feature_lists(cfg)

    def test_validate_model_feature_lists_raises_for_unknown_ranking_feature(self):
        cfg = load_config()
        ranking = {**cfg["model"]["ranking"], "customer_features": ["tenure", "MISSING"]}
        cfg = {**cfg, "model": {**cfg["model"], "ranking": ranking}}
        with pytest.raises(ValueError, match="MISSING"):
            validate_model_feature_lists(cfg)

    def test_validate_model_feature_lists_raises_for_duplicates(self):
        cfg = load_config()
        ranking = {**cfg["model"]["ranking"], "customer_features": ["tenure", "tenure"]}
        cfg = {**cfg, "model": {**cfg["model"], "ranking": ranking}}
        with pytest.raises(ValueError, match="duplicate"):
            validate_model_feature_lists(cfg)


# ---------------------------------------------------------------------------
# Fix 2 — encode_categorical_features() DataFrame-level utility
# ---------------------------------------------------------------------------


class TestEncodeCategoricalFeatures:
    _NUMERIC_SPEC = FeatureSpec(name="tenure", dtype="numeric")
    _PASSTHROUGH_SPEC = FeatureSpec(
        name="PaymentMethod",
        dtype="categorical",
        encoding="passthrough",
    )
    _ONE_HOT_SPEC = FeatureSpec(
        name="Contract",
        dtype="categorical",
        allowed_values=["Month-to-month", "One year", "Two year"],
        encoding="one_hot",
    )

    def test_numeric_passthrough_columns_preserved(self):
        df = pd.DataFrame([{"tenure": 12, "PaymentMethod": "Check"}])
        specs = [self._NUMERIC_SPEC, self._PASSTHROUGH_SPEC]
        result = encode_categorical_features(df, specs)
        assert "tenure" in result.columns
        assert "PaymentMethod" in result.columns
        assert result.loc[0, "tenure"] == 12
        assert result.loc[0, "PaymentMethod"] == "Check"

    def test_one_hot_encoding_expands_correctly(self):
        df = pd.DataFrame([
            {"Contract": "Month-to-month"},
            {"Contract": "One year"},
            {"Contract": "Two year"},
        ])
        result = encode_categorical_features(df, [self._ONE_HOT_SPEC])
        assert "contract_month_to_month" in result.columns
        assert "contract_one_year" in result.columns
        assert "contract_two_year" in result.columns
        assert result.loc[0, "contract_month_to_month"] == 1
        assert result.loc[0, "contract_one_year"] == 0
        assert result.loc[1, "contract_one_year"] == 1

    def test_prefix_applied_to_all_columns(self):
        df = pd.DataFrame([{"tenure": 5, "Contract": "One year"}])
        specs = [self._NUMERIC_SPEC, self._ONE_HOT_SPEC]
        result = encode_categorical_features(df, specs, prefix="customer_")
        assert "customer_tenure" in result.columns
        assert "customer_contract_one_year" in result.columns

    def test_index_preserved(self):
        df = pd.DataFrame([{"tenure": 1}, {"tenure": 2}], index=[10, 20])
        result = encode_categorical_features(df, [self._NUMERIC_SPEC])
        assert list(result.index) == [10, 20]

    def test_absent_columns_skipped_silently(self):
        df = pd.DataFrame([{"tenure": 5}])  # Contract absent
        specs = [self._NUMERIC_SPEC, self._ONE_HOT_SPEC]
        result = encode_categorical_features(df, specs)
        assert "tenure" in result.columns
        # Contract columns should be absent because the source column is missing
        assert "contract_month_to_month" not in result.columns

    def test_empty_dataframe_returns_correct_columns(self):
        df = pd.DataFrame(columns=["tenure"])
        result = encode_categorical_features(df, [self._NUMERIC_SPEC])
        assert "tenure" in result.columns
        assert len(result) == 0

    def test_one_hot_without_allowed_values_raises(self):
        spec = FeatureSpec(name="x", dtype="categorical", encoding="one_hot")
        df = pd.DataFrame([{"x": "foo"}])
        with pytest.raises(ValueError, match="allowed_values"):
            encode_categorical_features(df, [spec])

    def test_multiple_rows_consistent_output(self):
        df = pd.DataFrame([
            {"tenure": 10, "Contract": "Month-to-month"},
            {"tenure": 24, "Contract": "Two year"},
        ])
        specs = [self._NUMERIC_SPEC, self._ONE_HOT_SPEC]
        result = encode_categorical_features(df, specs)
        assert len(result) == 2
        assert result.loc[0, "tenure"] == 10
        assert result.loc[1, "contract_two_year"] == 1
        assert result.loc[1, "contract_month_to_month"] == 0


# ---------------------------------------------------------------------------
# Fix 3 — validate_values() on schema classes
# ---------------------------------------------------------------------------


class TestCustomerSchemaValidateValues:
    _SPECS = [
        FeatureSpec(name="tenure", dtype="numeric"),
        FeatureSpec(name="Contract", dtype="categorical", allowed_values=["Month-to-month", "One year", "Two year"]),
    ]

    def _schema(self) -> CustomerSchema:
        return CustomerSchema(features=self._SPECS)

    def _valid_df(self) -> pd.DataFrame:
        return pd.DataFrame([
            {"customer_id": "c1", "tenure": 12, "Contract": "Month-to-month"},
            {"customer_id": "c2", "tenure": 24, "Contract": "One year"},
        ])

    def test_valid_df_passes(self):
        self._schema().validate_values(self._valid_df())

    def test_missing_required_column_raises(self):
        df = self._valid_df().drop(columns=["tenure"])
        with pytest.raises(ValueError, match="tenure"):
            self._schema().validate_values(df)

    def test_invalid_categorical_value_raises(self):
        df = self._valid_df().copy()
        df.loc[0, "Contract"] = "Weekly"
        with pytest.raises(ValueError, match="Weekly"):
            self._schema().validate_values(df)

    def test_non_numeric_dtype_raises(self):
        df = self._valid_df().copy()
        df["tenure"] = df["tenure"].astype(str)
        with pytest.raises(ValueError, match="tenure"):
            self._schema().validate_values(df)

    def test_null_values_ignored_for_categorical_check(self):
        df = self._valid_df().copy()
        df.loc[0, "Contract"] = None
        self._schema().validate_values(df)  # must not raise


class TestProductSchemaValidateValues:
    _CATEGORY_SPEC = FeatureSpec(
        name="category", dtype="categorical", allowed_values=["Core", "Add-on"]
    )

    def _schema(self) -> ProductSchema:
        return ProductSchema(category=self._CATEGORY_SPEC)

    def _valid_df(self) -> pd.DataFrame:
        return pd.DataFrame([
            {"product_id": "p1", "category": "Core"},
            {"product_id": "p2", "category": "Add-on"},
        ])

    def test_valid_df_passes(self):
        self._schema().validate_values(self._valid_df())

    def test_invalid_category_raises(self):
        df = self._valid_df().copy()
        df.loc[0, "category"] = "Unknown"
        with pytest.raises(ValueError, match="Unknown"):
            self._schema().validate_values(df)

    def test_missing_product_id_raises(self):
        df = self._valid_df().drop(columns=["product_id"])
        with pytest.raises(ValueError, match="product_id"):
            self._schema().validate_values(df)


class TestInteractionSchemaValidateValues:
    def _schema(self) -> InteractionSchema:
        return InteractionSchema()

    def _valid_df(self) -> pd.DataFrame:
        return pd.DataFrame([{"customer_id": "c1", "product_id": "p1", "weight": 1.0}])

    def test_valid_df_passes(self):
        self._schema().validate_values(self._valid_df())

    def test_missing_customer_id_raises(self):
        df = self._valid_df().drop(columns=["customer_id"])
        with pytest.raises(ValueError, match="customer_id"):
            self._schema().validate_values(df)

    def test_non_numeric_weight_raises(self):
        df = self._valid_df().copy()
        df["weight"] = "heavy"
        with pytest.raises(ValueError, match="weight"):
            self._schema().validate_values(df)

    def test_absent_weight_column_is_fine(self):
        df = self._valid_df().drop(columns=["weight"])
        self._schema().validate_values(df)  # must not raise
