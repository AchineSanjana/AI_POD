"""Unit and integration tests for tenant onboarding CLI workflow."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from scripts.onboard_tenant import (
    handle_review_prompts,
    onboard_tenant,
    save_tenant_to_config,
)
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
from src.onboarding.profiler import profile_dataframe
from src.utils.config import get_tenant_config

# ---------------------------------------------------------------------------
# Synthetic Unit Tests
# ---------------------------------------------------------------------------


def test_save_tenant_to_config_temp(tmp_path: Path):
    """Verify safe saving and updating of tenant config blocks in YAML."""
    cfg_file = tmp_path / "config.yaml"
    init_data = {
        "tenants": {
            "existing_tenant": {"data_source": {"type": "csv", "path": "p.csv"}}
        }
    }
    cfg_file.write_text(yaml.safe_dump(init_data), encoding="utf-8")

    new_block = {
        "data_source": {"type": "csv", "path": "data/raw/new.csv"},
        "customers": {
            "id_column": "u_id",
            "features": [{"name": "age", "dtype": "numeric"}],
        },
        "products": {
            "derived_from": "interaction_source",
            "category_column": "category",
        },
        "interactions": {
            "source": "custom_services",
            "service_columns": ["feat_a"],
            "positive_values": ["Yes"],
            "negative_values": ["No"],
        },
    }

    save_tenant_to_config("new_tenant", new_block, config_path=cfg_file)

    with open(cfg_file, encoding="utf-8") as f:
        loaded = yaml.safe_load(f)

    assert "existing_tenant" in loaded["tenants"]
    assert "new_tenant" in loaded["tenants"]
    assert loaded["tenants"]["new_tenant"]["customers"]["id_column"] == "u_id"


def test_handle_review_prompts_interactive():
    """Verify prompt-driven adjustments for ambiguous columns."""
    df = pd.DataFrame(
        {
            "customer_id": [f"C_{i}" for i in range(20)],
            "status_flag": [0, 1] * 10,  # Ambiguous 0/1 numeric -> needs review
        }
    )

    report = profile_dataframe(df)
    initial_config = {
        "data_source": {"type": "csv", "path": "test.csv"},
        "customers": {
            "id_column": "customer_id",
            "features": [{"name": "status_flag", "dtype": "numeric"}],
        },
        "products": {
            "derived_from": "interaction_source",
            "category_column": "category",
        },
        "interactions": {
            "source": "custom_services",
            "service_columns": [],
            "positive_values": ["Yes"],
            "negative_values": ["No"],
        },
    }

    # Simulate user choosing option 2 (convert to categorical)
    prompt_responses = iter(["2"])
    adjusted = handle_review_prompts(
        report=report,
        config_block=initial_config,
        tenant_id="test_prompt_tenant",
        prompt_fn=lambda _: next(prompt_responses),
        non_interactive=False,
    )

    feature_map = {f["name"]: f for f in adjusted["customers"]["features"]}
    assert feature_map["status_flag"]["dtype"] == "categorical"


def test_onboard_tenant_non_interactive(tmp_path: Path):
    """Verify end-to-end non-interactive onboarding on synthetic data."""
    data_csv = tmp_path / "sample.csv"
    cfg_file = tmp_path / "config.yaml"

    df = pd.DataFrame(
        {
            "user_id": [f"U_{i}" for i in range(25)],
            "tenure": list(range(25)),
            "plan": ["Basic", "Pro"] * 12 + ["Basic"],
            "has_cloud": ["Yes", "No"] * 12 + ["Yes"],
        }
    )
    df.to_csv(data_csv, index=False)

    config_block = onboard_tenant(
        data_file=data_csv,
        tenant_id="sample_tenant",
        config_path=cfg_file,
        non_interactive=True,
        run_pipeline_flag=True,
    )

    assert config_block["customers"]["id_column"] == "user_id"

    # Verify saved file
    with open(cfg_file, encoding="utf-8") as f:
        saved_yaml = yaml.safe_load(f)
    assert "sample_tenant" in saved_yaml["tenants"]


def test_onboard_tenant_interactive_vs_auto_accept(tmp_path: Path):
    """Confirm both interactive and auto-accept modes produce valid configs."""
    data_csv = tmp_path / "fixture_data.csv"
    cfg_file = tmp_path / "config.yaml"
    log_dir = tmp_path / "onboarding_logs"

    df = pd.DataFrame(
        {
            "user_id": [f"UID_{i:03d}" for i in range(30)],
            "tenure_months": list(range(30)),
            "account_tier": ["Standard", "Premium"] * 15,
            "status_flag": [0, 1] * 15,  # Ambiguous 0/1 numeric
            "opt_in_newsletter": ["Yes", "No"] * 15,
        }
    )
    df.to_csv(data_csv, index=False)

    # 1. Interactive Mode with human adjustment (override status_flag -> categorical)
    prompt_responses = iter(["2", "y"])  # Option 2 for status_flag, Y to save
    interactive_cfg = onboard_tenant(
        data_file=data_csv,
        tenant_id="tenant_interactive",
        config_path=cfg_file,
        prompt_fn=lambda _: next(prompt_responses),
        non_interactive=False,
        auto_accept=False,
        log_dir=log_dir,
    )

    assert interactive_cfg["customers"]["id_column"] == "user_id"
    interactive_feat_map = {
        f["name"]: f for f in interactive_cfg["customers"]["features"]
    }
    assert interactive_feat_map["status_flag"]["dtype"] == "categorical"

    # 2. Auto-Accept Mode: accepts best guess (numeric) and writes audit log
    auto_cfg = onboard_tenant(
        data_file=data_csv,
        tenant_id="tenant_auto",
        config_path=cfg_file,
        non_interactive=False,  # auto_accept overrides non_interactive
        auto_accept=True,
        log_dir=log_dir,
    )

    assert auto_cfg["customers"]["id_column"] == "user_id"
    auto_feat_map = {f["name"]: f for f in auto_cfg["customers"]["features"]}
    assert auto_feat_map["status_flag"]["dtype"] == "numeric"

    # 3. Verify audit log file was written
    audit_file = log_dir / "tenant_auto_config_review.txt"
    assert audit_file.exists()
    audit_content = audit_file.read_text(encoding="utf-8")
    assert "Detected 30 rows" in audit_content
    assert "status_flag" in audit_content
    assert "user_id" in audit_content

    # 4. Verify both tenant configs can run with GenericConfigAdapter
    with open(cfg_file, encoding="utf-8") as f:
        full_saved = yaml.safe_load(f)

    # Run interactive tenant
    t_cfg_interactive = get_tenant_config(full_saved, "tenant_interactive")
    adapter_int = GenericConfigAdapter(t_cfg_interactive)
    cust_int, prod_int, inter_int = adapter_int.run()
    assert len(cust_int) == 30

    # Run auto-accept tenant
    t_cfg_auto = get_tenant_config(full_saved, "tenant_auto")
    adapter_auto = GenericConfigAdapter(t_cfg_auto)
    cust_auto, prod_auto, inter_auto = adapter_auto.run()
    assert len(cust_auto) == 30


# ---------------------------------------------------------------------------
# Telco Dataset End-to-End Onboarding Test
# ---------------------------------------------------------------------------


def test_onboard_tenant_telco_e2e(tmp_path: Path):
    """Verify onboarding on raw Telco CSV and executing GenericConfigAdapter."""
    telco_path = Path("data/raw/telco_customer_churn.csv")
    if not telco_path.exists():
        pytest.skip("data/raw/telco_customer_churn.csv not found")

    cfg_file = tmp_path / "config.yaml"

    # Onboard telco_corp with manual override converting SeniorCitizen to categorical
    config_block = onboard_tenant(
        data_file=telco_path,
        tenant_id="telco_corp",
        config_path=cfg_file,
        non_interactive=True,
        overrides={"SeniorCitizen": "categorical"},
        run_pipeline_flag=False,
    )

    assert config_block["customers"]["id_column"] == "customerID"

    feature_map = {f["name"]: f for f in config_block["customers"]["features"]}
    assert feature_map["SeniorCitizen"]["dtype"] == "categorical"

    # Run adapter using the newly saved configuration
    with open(cfg_file, encoding="utf-8") as f:
        saved_cfg = yaml.safe_load(f)

    tenant_cfg = get_tenant_config(saved_cfg, "telco_corp")
    adapter = GenericConfigAdapter(tenant_cfg)
    customers, products, interactions = adapter.run()

    assert len(customers) == 7043
    assert "customer_id" in customers.columns
    assert "SeniorCitizen" in customers.columns
    assert len(products) > 0
    assert len(interactions) > 0
