"""Tests for tenant configuration validation errors and warnings."""

import logging
import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from src.core.schema import FeatureSpec
# pyrefly: ignore [missing-import]
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
# pyrefly: ignore [missing-import]
from src.utils.config import (
    DataSourceConfig,
    InteractionSourceConfig,
    TenantConfig,
    TenantCustomersConfig,
    TenantInteractionsConfig,
    TenantProductsConfig,
)


def _make_tenant_config(
    csv_path: str,
    id_column: str = "user_id",
    allowed_values: list[str] | None = None,
    service_columns: list[str] | None = None,
) -> TenantConfig:
    return TenantConfig(
        tenant_id="broken_tenant",
        data_source=DataSourceConfig(type="csv", path=csv_path),
        customers=TenantCustomersConfig(
            id_column=id_column,
            features=[
                FeatureSpec(
                    name="plan_type",
                    dtype="categorical",
                    allowed_values=allowed_values or ["Basic", "Pro"],
                )
            ],
        ),
        products=TenantProductsConfig(derived_from="interaction_source", category_column="category"),
        interactions=TenantInteractionsConfig(
            source="custom_services",
            interaction_source=InteractionSourceConfig(
                service_columns=service_columns or ["service1"],
                positive_values=["Yes"],
                negative_values=["No"],
            ),
        ),
    )


def test_missing_id_column_raises_clear_error(tmp_path):
    """Verify missing id_column raises a clear, actionable ValueError."""
    df = pd.DataFrame({"user_id": ["u1", "u2"], "plan_type": ["Basic", "Pro"], "service1": ["Yes", "No"]})
    csv_file = tmp_path / "data.csv"
    df.to_csv(csv_file, index=False)

    tenant_cfg = _make_tenant_config(csv_path=str(csv_file), id_column="wrong_id")
    adapter = GenericConfigAdapter(tenant_cfg)

    with pytest.raises(ValueError, match="Column 'wrong_id' declared as customers.id_column not found in raw data"):
        adapter.to_customers()


def test_unexpected_categorical_values_warns(tmp_path, caplog):
    """Verify unexpected categorical values generate a warning without crashing."""
    df = pd.DataFrame(
        {"user_id": ["u1", "u2"], "plan_type": ["Basic", "CustomTier"], "service1": ["Yes", "No"]}
    )
    csv_file = tmp_path / "data.csv"
    df.to_csv(csv_file, index=False)

    tenant_cfg = _make_tenant_config(csv_path=str(csv_file), allowed_values=["Basic", "Pro"])
    adapter = GenericConfigAdapter(tenant_cfg)

    with caplog.at_level(logging.WARNING):
        customers = adapter.to_customers()
        assert isinstance(customers, pd.DataFrame)
        assert "Feature 'plan_type' contains values not in allowed_values: ['CustomTier']" in caplog.text


def test_missing_interaction_source_column_raises_clear_error(tmp_path):
    """Verify missing interaction_source column raises a clear, actionable ValueError."""
    df = pd.DataFrame({"user_id": ["u1", "u2"], "plan_type": ["Basic", "Pro"], "service1": ["Yes", "No"]})
    csv_file = tmp_path / "data.csv"
    df.to_csv(csv_file, index=False)

    tenant_cfg = _make_tenant_config(
        csv_path=str(csv_file),
        service_columns=["service1", "non_existent_service"],
    )
    adapter = GenericConfigAdapter(tenant_cfg)

    with pytest.raises(
        ValueError,
        match="Interaction source column 'non_existent_service' not found in raw data",
    ):
        adapter.to_interactions()
