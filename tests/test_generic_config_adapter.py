"""Tests for GenericConfigAdapter."""

import json
import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from src.core.schema import FeatureSpec
# pyrefly: ignore [missing-import]
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
# pyrefly: ignore [missing-import]
from src.data.adapters.telco_adapter import TelcoAdapter
# pyrefly: ignore [missing-import]
from src.utils.config import (
    DataSourceConfig,
    TenantConfig,
    TenantCustomersConfig,
    TenantInteractionsConfig,
    TenantProductsConfig,
    get_tenant_config,
    load_config,
)


def test_generic_config_adapter_with_telco_default():
    """Verify GenericConfigAdapter works with the telco_default tenant config."""
    cfg = load_config()
    tenant_cfg = get_tenant_config(cfg, "telco_default")
    adapter = GenericConfigAdapter(tenant_cfg)

    raw = adapter.load_raw()
    assert isinstance(raw, pd.DataFrame)
    assert not raw.empty

    customers = adapter.to_customers()
    assert isinstance(customers, pd.DataFrame)
    assert "customer_id" in customers.columns
    assert "tenure" in customers.columns
    assert "Contract" in customers.columns

    products = adapter.to_products()
    assert isinstance(products, pd.DataFrame)
    assert "product_id" in products.columns
    assert "category" in products.columns

    interactions = adapter.to_interactions()
    assert isinstance(interactions, pd.DataFrame)
    assert "customer_id" in interactions.columns
    assert "product_id" in interactions.columns


def test_generic_config_adapter_matches_telco_adapter():
    """Verify GenericConfigAdapter output is bit-for-bit identical to TelcoAdapter."""
    cfg = load_config()
    tenant_cfg = get_tenant_config(cfg, "telco_default")

    gen_adapter = GenericConfigAdapter(tenant_cfg)
    telco_adapter = TelcoAdapter(config=cfg)

    gen_cust = gen_adapter.to_customers()
    telco_cust = telco_adapter.to_customers()
    pd.testing.assert_frame_equal(gen_cust, telco_cust)

    gen_prod = gen_adapter.to_products()
    telco_prod = telco_adapter.to_products()
    pd.testing.assert_frame_equal(gen_prod, telco_prod)

    gen_inter = gen_adapter.to_interactions()
    telco_inter = telco_adapter.to_interactions()
    pd.testing.assert_frame_equal(gen_inter, telco_inter)


def test_generic_config_adapter_json_data_source(tmp_path):
    """Verify GenericConfigAdapter correctly loads and processes JSON data sources."""
    data = [
        {"usr_id": "u1", "age": "30", "plan": "basic"},
        {"usr_id": "u2", "age": "45", "plan": "pro"},
    ]
    json_file = tmp_path / "test_data.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    tenant_cfg = TenantConfig(
        tenant_id="json_tenant",
        data_source=DataSourceConfig(type="json", path=str(json_file)),
        customers=TenantCustomersConfig(
            id_column="usr_id",
            features=[
                FeatureSpec(name="age", dtype="numeric"),
                FeatureSpec(name="plan", dtype="categorical"),
            ],
        ),
        products=TenantProductsConfig(derived_from="none", category_column="category"),
        interactions=TenantInteractionsConfig(source="none"),
    )

    adapter = GenericConfigAdapter(tenant_cfg)
    raw = adapter.load_raw()
    assert len(raw) == 2

    customers = adapter.to_customers()
    assert list(customers.columns) == ["customer_id", "age", "plan"]
    assert customers.loc[0, "customer_id"] == "u1"
    assert customers.loc[0, "age"] == 30.0
