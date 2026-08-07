"""Tests for tenant configuration parsing and validation in src/utils/config.py."""

import pytest

# pyrefly: ignore [missing-import]
from src.core.schema import FeatureSpec
# pyrefly: ignore [missing-import]
from src.utils.config import (
    DataSourceConfig,
    InteractionSourceConfig,
    TenantConfig,
    TenantCustomersConfig,
    TenantInteractionsConfig,
    TenantProductsConfig,
    get_tenant_config,
    load_config,
)


def test_get_tenant_config_telco_default():
    """Verify telco_default tenant block matches everything hardcoded in TelcoAdapter."""
    cfg = load_config()
    tenant_cfg = get_tenant_config(cfg, "telco_default")

    assert isinstance(tenant_cfg, TenantConfig)
    assert tenant_cfg.tenant_id == "telco_default"

    # 1. data_source matches raw CSV input for load_raw_telco
    assert isinstance(tenant_cfg.data_source, DataSourceConfig)
    assert tenant_cfg.data_source.type == "csv"
    assert tenant_cfg.data_source.path == "data/raw/telco_customer_churn.csv"

    # 2. customers matches TelcoAdapter raw ID column and features
    assert isinstance(tenant_cfg.customers, TenantCustomersConfig)
    assert tenant_cfg.customers.id_column == "customerID"
    assert isinstance(tenant_cfg.customers.features, list)
    feature_names = [f.name for f in tenant_cfg.customers.features]
    assert "tenure" in feature_names
    assert "MonthlyCharges" in feature_names
    assert "SeniorCitizen" in feature_names
    assert "Contract" in feature_names

    contract_spec = next(f for f in tenant_cfg.customers.features if f.name == "Contract")
    assert contract_spec.dtype == "categorical"
    assert contract_spec.allowed_values == ["Month-to-month", "One year", "Two year"]
    assert contract_spec.encoding == "one_hot"

    # 3. products matches TelcoAdapter derivation from interaction_source
    assert isinstance(tenant_cfg.products, TenantProductsConfig)
    assert tenant_cfg.products.derived_from == "interaction_source"
    assert tenant_cfg.products.category_column == "category"

    # 4. interactions references interaction_source block
    assert isinstance(tenant_cfg.interactions, TenantInteractionsConfig)
    assert tenant_cfg.interactions.source == "interaction_source"
    assert isinstance(tenant_cfg.interactions.interaction_source, InteractionSourceConfig)

    isc = tenant_cfg.interactions.interaction_source
    assert isc.service_columns == [
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
    assert isc.positive_values == ["Yes", "DSL", "Fiber optic"]
    assert isc.negative_values == ["No", "No internet service", "No phone service"]


def test_get_tenant_config_missing_top_level_tenants_raises():
    cfg = {}
    with pytest.raises(KeyError, match="tenants"):
        get_tenant_config(cfg, "telco_default")


def test_get_tenant_config_missing_tenant_id_raises():
    cfg = load_config()
    with pytest.raises(KeyError, match="nonexistent_tenant"):
        get_tenant_config(cfg, "nonexistent_tenant")


@pytest.mark.parametrize(
    "incomplete_block, expected_match",
    [
        (
            {"customers": {}, "products": {}, "interactions": {}},
            "data_source",
        ),
        (
            {"data_source": {"type": "csv"}, "customers": {}, "products": {}, "interactions": {}},
            "path",
        ),
        (
            {
                "data_source": {"type": "csv", "path": "p"},
                "customers": {"id_column": "id"},
                "products": {},
                "interactions": {},
            },
            "features",
        ),
        (
            {
                "data_source": {"type": "csv", "path": "p"},
                "customers": {"id_column": "id", "features": []},
                "products": {"derived_from": "x"},
                "interactions": {},
            },
            "category_column",
        ),
        (
            {
                "data_source": {"type": "csv", "path": "p"},
                "customers": {"id_column": "id", "features": []},
                "products": {"derived_from": "x", "category_column": "c"},
                "interactions": {},
            },
            "source",
        ),
    ],
)
def test_get_tenant_config_missing_subfields_raises(incomplete_block: dict, expected_match: str):
    cfg = {"tenants": {"t1": incomplete_block}}
    with pytest.raises(KeyError, match=expected_match):
        get_tenant_config(cfg, "t1")
