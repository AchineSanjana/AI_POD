"""Tests for TelcoAdapter.

Strategy
--------
- Tests that don't need the real CSV file use a minimal synthetic ``raw_df``
  fixture that has exactly the columns reshape_telco.py would see.
- Tests that need the full dataset are marked ``@pytest.mark.integration``
  and skipped automatically when the CSV file is absent.

All assertions compare output against the original ``reshape_telco.py``
functions so we can prove bit-for-bit equivalence with the existing pipeline.
"""

from __future__ import annotations

import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from src.core.schema import CustomerSchema, FeatureSpec, InteractionSchema, ProductSchema
# pyrefly: ignore [missing-import]
from src.data.adapters.telco_adapter import TelcoAdapter, _binary_service_columns, _humanize
# pyrefly: ignore [missing-import]
from src.data.reshape_telco import (
    BINARY_SERVICE_COLUMNS,
    NEGATIVE_VALUES,
    build_customers_table,
    build_interactions_table,
    build_products_table,
)
# pyrefly: ignore [missing-import]
from src.utils.config import (
    build_customer_schema_from_config,
    build_product_schema_from_config,
    get_interaction_source_config,
    load_config,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_RAW_COLUMNS = [
    "customerID",
    "gender",
    "SeniorCitizen",
    "Partner",
    "Dependents",
    "tenure",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
    "MonthlyCharges",
    "TotalCharges",
    "Churn",
    # service columns
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
]


def _make_raw_df() -> pd.DataFrame:
    """Two synthetic customer rows that exercise all code paths in to_interactions()."""
    return pd.DataFrame(
        [
            {
                "customerID": "C001",
                "gender": "Male",
                "SeniorCitizen": 0,
                "Partner": "Yes",
                "Dependents": "No",
                "tenure": 12,
                "Contract": "Month-to-month",
                "PaperlessBilling": "Yes",
                "PaymentMethod": "Electronic check",
                "MonthlyCharges": 70.0,
                "TotalCharges": 840.0,
                "Churn": "No",
                # subscribed to phone + DSL internet + online security
                "PhoneService": "Yes",
                "MultipleLines": "No",
                "InternetService": "DSL",
                "OnlineSecurity": "Yes",
                "OnlineBackup": "No",
                "DeviceProtection": "No",
                "TechSupport": "No internet service",
                "StreamingTV": "No internet service",
                "StreamingMovies": "No internet service",
            },
            {
                "customerID": "C002",
                "gender": "Female",
                "SeniorCitizen": 1,
                "Partner": "No",
                "Dependents": "No",
                "tenure": 24,
                "Contract": "One year",
                "PaperlessBilling": "No",
                "PaymentMethod": "Mailed check",
                "MonthlyCharges": 95.0,
                "TotalCharges": 2280.0,
                "Churn": "Yes",
                # subscribed to fiber optic + streaming TV + movies
                "PhoneService": "No",
                "MultipleLines": "No phone service",
                "InternetService": "Fiber optic",
                "OnlineSecurity": "No",
                "OnlineBackup": "No",
                "DeviceProtection": "Yes",
                "TechSupport": "No",
                "StreamingTV": "Yes",
                "StreamingMovies": "Yes",
            },
        ]
    )


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


@pytest.fixture(scope="module")
def adapter(cfg: dict) -> TelcoAdapter:
    return TelcoAdapter(
        config=cfg,
        customer_schema=build_customer_schema_from_config(cfg),
        product_schema=build_product_schema_from_config(cfg),
    )


@pytest.fixture(scope="module")
def raw_df() -> pd.DataFrame:
    return _make_raw_df()


def _adapter_with_raw(raw: pd.DataFrame, cfg: dict) -> TelcoAdapter:
    """Return a TelcoAdapter whose _raw is already set (no file I/O)."""
    a = TelcoAdapter(
        config=cfg,
        customer_schema=build_customer_schema_from_config(cfg),
        product_schema=build_product_schema_from_config(cfg),
    )
    a._raw = raw
    return a


# ---------------------------------------------------------------------------
# Unit tests — no file I/O
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_humanize_phone_service(self) -> None:
        assert _humanize("PhoneService") == "Phone Service"

    def test_humanize_streaming_tv(self) -> None:
        assert _humanize("StreamingTV") == "Streaming TV"

    def test_humanize_online_security(self) -> None:
        assert _humanize("OnlineSecurity") == "Online Security"

    def test_humanize_matches_reshape_telco(self) -> None:
        """_humanize in TelcoAdapter must produce identical output to reshape_telco._humanize."""
        from src.data.reshape_telco import _humanize as _orig_humanize

        for col in BINARY_SERVICE_COLUMNS:
            assert _humanize(col) == _orig_humanize(col), f"Mismatch for {col!r}"

    def test_binary_service_columns_excludes_internet_service(self, cfg: dict) -> None:
        isc = get_interaction_source_config(cfg)
        binary = _binary_service_columns(isc)
        assert "InternetService" not in binary

    def test_binary_service_columns_matches_reshape_telco_constant(
        self, cfg: dict
    ) -> None:
        isc = get_interaction_source_config(cfg)
        assert set(_binary_service_columns(isc)) == set(BINARY_SERVICE_COLUMNS)


class TestToCustomers:
    def test_returns_dataframe(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        assert isinstance(a.to_customers(), pd.DataFrame)

    def test_customer_id_column_present(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        assert "customer_id" in a.to_customers().columns

    def test_customer_id_column_not_raw(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        """The raw 'customerID' must be renamed, not kept alongside."""
        a = _adapter_with_raw(raw_df, cfg)
        assert "customerID" not in a.to_customers().columns

    def test_customer_id_values_preserved(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        assert list(a.to_customers()["customer_id"]) == ["C001", "C002"]

    def test_row_count_matches_raw(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        assert len(a.to_customers()) == len(raw_df)

    def test_passes_schema_validate(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        """validate_values is called inside to_customers() — must not raise."""
        a = _adapter_with_raw(raw_df, cfg)
        # Should not raise
        a.to_customers()

    def test_no_service_columns_leaked(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        service_in_customers = set(BINARY_SERVICE_COLUMNS) & set(a.to_customers().columns)
        assert not service_in_customers, f"Service columns leaked: {service_in_customers}"


class TestToProducts:
    def test_returns_dataframe(self, adapter: TelcoAdapter) -> None:
        assert isinstance(adapter.to_products(), pd.DataFrame)

    def test_required_columns(self, adapter: TelcoAdapter) -> None:
        df = adapter.to_products()
        assert {"product_id", "product_name", "category"}.issubset(df.columns)

    def test_internet_service_split_present(self, adapter: TelcoAdapter) -> None:
        ids = set(adapter.to_products()["product_id"])
        assert "InternetService_DSL" in ids
        assert "InternetService_Fiber" in ids

    def test_internet_service_raw_not_present(self, adapter: TelcoAdapter) -> None:
        assert "InternetService" not in set(adapter.to_products()["product_id"])

    def test_category_values_only_core_or_addon(self, adapter: TelcoAdapter) -> None:
        cats = set(adapter.to_products()["category"].unique())
        assert cats <= {"Core", "Add-on"}

    def test_product_count_matches_reshape_telco(self, adapter: TelcoAdapter) -> None:
        original = build_products_table()
        assert len(adapter.to_products()) == len(original)

    def test_product_ids_match_reshape_telco(self, adapter: TelcoAdapter) -> None:
        original_ids = set(build_products_table()["product_id"])
        adapter_ids = set(adapter.to_products()["product_id"])
        assert adapter_ids == original_ids, (
            f"Extra:   {adapter_ids - original_ids}\n"
            f"Missing: {original_ids - adapter_ids}"
        )

    def test_categories_match_reshape_telco(self, adapter: TelcoAdapter) -> None:
        original = build_products_table().set_index("product_id")["category"]
        adapted = adapter.to_products().set_index("product_id")["category"]
        for pid in original.index:
            assert adapted[pid] == original[pid], (
                f"Category mismatch for {pid!r}: "
                f"original={original[pid]!r}, adapter={adapted[pid]!r}"
            )


class TestToInteractions:
    def test_returns_dataframe(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        assert isinstance(a.to_interactions(), pd.DataFrame)

    def test_required_columns(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        df = a.to_interactions()
        assert {"customer_id", "product_id"}.issubset(df.columns)

    def test_negative_values_excluded(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        """No row should have a product_id for a column where the customer said 'No'."""
        a = _adapter_with_raw(raw_df, cfg)
        interactions = a.to_interactions()
        # C001 has PhoneService=Yes, OnlineSecurity=Yes — but TechSupport=No internet service
        c001_products = set(
            interactions.loc[interactions["customer_id"] == "C001", "product_id"]
        )
        assert "TechSupport" not in c001_products
        assert "StreamingTV" not in c001_products

    def test_positive_values_included(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        interactions = a.to_interactions()
        c001_products = set(
            interactions.loc[interactions["customer_id"] == "C001", "product_id"]
        )
        assert "PhoneService" in c001_products
        assert "OnlineSecurity" in c001_products

    def test_dsl_internet_mapped_correctly(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        interactions = a.to_interactions()
        c001_products = set(
            interactions.loc[interactions["customer_id"] == "C001", "product_id"]
        )
        assert "InternetService_DSL" in c001_products
        assert "InternetService_Fiber" not in c001_products

    def test_fiber_internet_mapped_correctly(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        interactions = a.to_interactions()
        c002_products = set(
            interactions.loc[interactions["customer_id"] == "C002", "product_id"]
        )
        assert "InternetService_Fiber" in c002_products
        assert "InternetService_DSL" not in c002_products

    def test_passes_schema_validate(self, raw_df: pd.DataFrame, cfg: dict) -> None:
        a = _adapter_with_raw(raw_df, cfg)
        # Should not raise
        a.to_interactions()

    def test_matches_reshape_telco_on_synthetic_data(
        self, raw_df: pd.DataFrame, cfg: dict
    ) -> None:
        """Row-for-row comparison against the original build_interactions_table()."""
        a = _adapter_with_raw(raw_df, cfg)
        adapter_df = (
            a.to_interactions()
            .sort_values(["customer_id", "product_id"])
            .reset_index(drop=True)
        )
        original_df = (
            build_interactions_table(raw_df)
            .sort_values(["customer_id", "product_id"])
            .reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(adapter_df, original_df)


class TestEnsureRaw:
    def test_load_raw_called_automatically(self, cfg: dict) -> None:
        """_ensure_raw() calls load_raw() when _raw is None — needs real CSV."""
        from src.utils.config import resolve_path

        raw_path = (
            resolve_path(cfg["paths"]["raw_dir"]) / cfg["paths"]["telco_raw_file"]
        )
        if not raw_path.exists():
            pytest.skip("Raw CSV not present — skipping auto-load test")

        a = TelcoAdapter(config=cfg)
        # _raw is None until load_raw() / _ensure_raw() is called
        assert a._raw is None
        a.to_customers()  # triggers _ensure_raw()
        assert a._raw is not None


# ---------------------------------------------------------------------------
# Integration tests — require the real CSV file
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAdapterVsReshapeTelcoIntegration:
    """Bit-for-bit equivalence with the original reshape_telco.py functions."""

    @pytest.fixture(autouse=True)
    def require_csv(self, cfg: dict) -> None:
        from src.utils.config import resolve_path

        raw_path = (
            resolve_path(cfg["paths"]["raw_dir"]) / cfg["paths"]["telco_raw_file"]
        )
        if not raw_path.exists():
            pytest.skip("Raw Telco CSV not present")

    def test_customers_matches_reshape_telco(self, adapter: TelcoAdapter) -> None:
        adapter.load_raw()
        from src.data.reshape_telco import build_customers_table

        original = build_customers_table(adapter._raw).reset_index(drop=True)
        adapted = adapter.to_customers().reset_index(drop=True)
        pd.testing.assert_frame_equal(adapted, original)

    def test_products_matches_reshape_telco(self, adapter: TelcoAdapter) -> None:
        original = build_products_table().reset_index(drop=True)
        adapted = adapter.to_products().reset_index(drop=True)
        pd.testing.assert_frame_equal(adapted, original)

    def test_interactions_matches_reshape_telco(self, adapter: TelcoAdapter) -> None:
        adapter.load_raw()
        original = (
            build_interactions_table(adapter._raw)
            .sort_values(["customer_id", "product_id"])
            .reset_index(drop=True)
        )
        adapted = (
            adapter.to_interactions()
            .sort_values(["customer_id", "product_id"])
            .reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(adapted, original)
