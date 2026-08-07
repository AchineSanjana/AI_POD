"""Test verifying multi-tenant pipeline isolation across processed data and trained models."""

import sys
from pathlib import Path

import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from scripts import run_pipeline
# pyrefly: ignore [missing-import]
from src.utils.config import resolve_path


def test_multi_tenant_pipeline_isolation(monkeypatch):
    """Verify running pipeline for telco_default and fixture_ecommerce produces isolated outputs."""
    # 1. Run pipeline for telco_default
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--tenant_id", "telco_default"])
    run_pipeline.main()

    # 2. Run pipeline for fixture_ecommerce
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--tenant_id", "fixture_ecommerce"])
    run_pipeline.main()

    # 3. Confirm expected output directory structures exist
    telco_proc_dir = resolve_path(Path("data") / "processed" / "telco_default")
    ecom_proc_dir = resolve_path(Path("data") / "processed" / "fixture_ecommerce")

    telco_model_dir = resolve_path(Path("models") / "telco_default")
    ecom_model_dir = resolve_path(Path("models") / "fixture_ecommerce")

    assert (telco_proc_dir / "customers.csv").exists()
    assert (telco_proc_dir / "products.csv").exists()
    assert (telco_proc_dir / "interactions.csv").exists()
    assert (telco_model_dir / "final_model.joblib").exists()

    assert (ecom_proc_dir / "customers.csv").exists()
    assert (ecom_proc_dir / "products.csv").exists()
    assert (ecom_proc_dir / "interactions.csv").exists()
    assert (ecom_model_dir / "final_model.joblib").exists()

    # 4. Load output customer tables and assert no cross-contamination
    telco_cust = pd.read_csv(telco_proc_dir / "customers.csv")
    ecom_cust = pd.read_csv(ecom_proc_dir / "customers.csv")

    telco_ids = set(telco_cust["customer_id"].astype(str))
    ecom_ids = set(ecom_cust["customer_id"].astype(str))

    assert telco_ids.isdisjoint(ecom_ids), "Cross-contamination detected between tenant customer_ids"
    assert all(cid.startswith("usr_") for cid in ecom_ids)
    assert not any(cid.startswith("usr_") for cid in telco_ids)
