"""Unit and integration tests for tenant config generator and review summaries."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.data.adapters.generic_config_adapter import GenericConfigAdapter
from src.onboarding.config_generator import (
    generate_review_summary,
    generate_tenant_config,
)
from src.onboarding.profiler import profile_dataframe
from src.utils.config import get_tenant_config, load_config

# ---------------------------------------------------------------------------
# Synthetic Unit Tests
# ---------------------------------------------------------------------------


def test_generate_tenant_config_empty_raises():
    """Verify that an empty profile report raises ValueError."""
    with pytest.raises(ValueError, match="Cannot generate tenant config"):
        generate_tenant_config([], "test_tenant", "data/raw/test.csv")


def test_generate_tenant_config_synthetic():
    """Verify config generation on a synthetic dataset profile."""
    df = pd.DataFrame(
        {
            "user_id": [f"U_{i}" for i in range(50)],
            "age": [20 + i for i in range(50)],
            "plan_type": ["Basic", "Pro"] * 25,
            "has_feature_a": ["Yes", "No"] * 25,
            "has_feature_b": ["Yes", "No"] * 25,
        }
    )

    report = profile_dataframe(df)
    config = generate_tenant_config(report, "synth_tenant", "data/raw/synth.csv")

    assert config["data_source"]["type"] == "csv"
    assert config["data_source"]["path"] == "data/raw/synth.csv"
    assert config["customers"]["id_column"] == "user_id"

    feature_names = [f["name"] for f in config["customers"]["features"]]
    assert "user_id" not in feature_names
    assert "age" in feature_names
    assert "plan_type" in feature_names

    # Service columns detected from binary columns
    service_cols = config["interactions"]["service_columns"]
    assert "has_feature_a" in service_cols
    assert "has_feature_b" in service_cols

    # Positive and negative values
    assert "Yes" in config["interactions"]["positive_values"]
    assert "No" in config["interactions"]["negative_values"]

    # Segmentation configured on numeric candidate
    assert config.get("segmentation") is not None
    assert config["segmentation"]["field"] == "age"

    # YAML serialization
    yaml_str = yaml.safe_dump(config)
    assert isinstance(yaml_str, str)
    assert "user_id" in yaml_str


def test_generate_review_summary_synthetic():
    """Verify plain-English review summary generation."""
    # 1. Empty report
    assert "No data columns found" in generate_review_summary([])

    # 2. Report with review-needed column
    df = pd.DataFrame(
        {
            "customer_id": [f"C_{i}" for i in range(20)],
            "tenure": list(range(20)),
            "contract": ["Month-to-month", "One year"] * 10,
            "has_phone": ["Yes", "No"] * 10,
            "status_code": [0, 1] * 10,  # 0/1 numeric flag -> needs review
        }
    )

    report = profile_dataframe(df)
    summary = generate_review_summary(report)

    assert "Detected 20 rows across 5 columns." in summary
    assert "Customer ID column: 'customer_id'" in summary
    assert "high confidence" in summary
    assert "Found 2 numeric customer fields: tenure, status_code." in summary
    assert "contract (2 values: Month-to-month, One year)" in summary
    assert "Found 2 binary service-style columns" in summary
    assert "1 column needs your review before we proceed:" in summary
    assert "- 'status_code': Only 2 distinct numeric values found" in summary


# ---------------------------------------------------------------------------
# Telco Dataset Benchmark & Comparison Tests
# ---------------------------------------------------------------------------


def test_generate_tenant_config_telco_vs_default():
    """Run config generator on raw Telco CSV and compare against telco_default."""
    telco_path = Path("data/raw/telco_customer_churn.csv")
    if not telco_path.exists():
        pytest.skip("data/raw/telco_customer_churn.csv not found")

    # 1. Profile raw CSV bypassing telco_default config
    raw_df = pd.read_csv(telco_path)
    profile_report = profile_dataframe(raw_df)

    # 2. Auto-generate tenant config
    autogen_config_block = generate_tenant_config(
        profile_report=profile_report,
        tenant_id="telco_autogen",
        data_source_path="data/raw/telco_customer_churn.csv",
    )

    assert autogen_config_block["customers"]["id_column"] == "customerID"
    feature_names = [f["name"] for f in autogen_config_block["customers"]["features"]]
    assert "tenure" in feature_names

    # 3. Parse into TenantConfig and run GenericConfigAdapter for AUTO-GENERATED tenant
    full_config_autogen = {"tenants": {"telco_autogen": autogen_config_block}}
    tenant_cfg_autogen = get_tenant_config(full_config_autogen, "telco_autogen")
    adapter_autogen = GenericConfigAdapter(tenant_cfg_autogen)

    autogen_customers, autogen_products, autogen_interactions = adapter_autogen.run()

    # 4. Run GenericConfigAdapter with manually-configured telco_default
    base_cfg = load_config()
    tenant_cfg_manual = get_tenant_config(base_cfg, "telco_default")
    adapter_manual = GenericConfigAdapter(tenant_cfg_manual)

    manual_customers, manual_products, manual_interactions = adapter_manual.run()

    # 5. Compare Customers table
    assert len(autogen_customers) == len(manual_customers) == 7043
    assert autogen_customers["customer_id"].equals(manual_customers["customer_id"])

    # Check that manual customer features are all present in autogen customer table
    for col in manual_customers.columns:
        assert col in autogen_customers.columns, f"Expected {col} in autogen customers"

    # 6. Compare Products & Interactions and report differences
    differences: list[str] = []

    manual_isc = tenant_cfg_manual.interactions.interaction_source
    autogen_isc = tenant_cfg_autogen.interactions.interaction_source
    assert manual_isc is not None
    assert autogen_isc is not None

    manual_service_cols = set(manual_isc.service_columns)
    autogen_service_cols = set(autogen_isc.service_columns)

    added_service_cols = autogen_service_cols - manual_service_cols
    if added_service_cols:
        differences.append(
            f"Autogen detected additional binary service columns: "
            f"{sorted(added_service_cols)} (manual config restricted to 9 services)"
        )

    autogen_prod_count = len(autogen_products)
    manual_prod_count = len(manual_products)
    if autogen_prod_count != manual_prod_count:
        differences.append(
            f"Product count differs: autogen has {autogen_prod_count} products, "
            f"manual has {manual_prod_count} products"
        )

    # Invariant: All manual products exist in autogen products
    assert manual_service_cols.issubset(autogen_service_cols)
    assert len(autogen_interactions) >= len(manual_interactions)


def test_generate_review_summary_telco():
    """Verify plain-English review summary on real Telco dataset."""
    telco_path = Path("data/raw/telco_customer_churn.csv")
    if not telco_path.exists():
        pytest.skip("data/raw/telco_customer_churn.csv not found")

    raw_df = pd.read_csv(telco_path)
    profile_report = profile_dataframe(raw_df)
    summary = generate_review_summary(profile_report)

    # Check that summary is readable and contains key sections
    assert "Detected 7,043 rows across 21 columns." in summary
    assert "Customer ID column: 'customerID'" in summary
    assert "tenure" in summary
    assert "MonthlyCharges" in summary
    assert "Contract" in summary
    assert "SeniorCitizen" in summary
    assert (
        "needs your review before we proceed" in summary
        or "need your review before we proceed" in summary
    )

    print("\n--- Telco Dataset Stakeholder Review Summary ---")
    print(summary)
