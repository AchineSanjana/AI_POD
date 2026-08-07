"""End-to-end multi-tenant API tests verifying pipeline execution, recommendation parity, and cross-tenant isolation."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

# pyrefly: ignore [missing-import]
from scripts import run_pipeline
# pyrefly: ignore [missing-import]
from src.api.app import app
# pyrefly: ignore [missing-import]
from src.api.recommendations import clear_model_cache, get_model_for_tenant
# pyrefly: ignore [missing-import]
from src.utils.config import resolve_path


client = TestClient(app)


def test_api_multitenancy_telco_ecommerce_isolation(monkeypatch):
    """
    1. Run pipeline for telco_default and confirm API returns expected baseline recommendations.
    2. Run pipeline for fixture_ecommerce and confirm recommendations are scoped strictly to e-commerce catalog.
    3. Confirm cross-tenant customer queries return 404 errors with zero cross-contamination.
    """
    # 1. Run pipeline for both tenants to ensure fresh models and datasets exist
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--tenant_id", "telco_default"])
    run_pipeline.main()

    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--tenant_id", "fixture_ecommerce"])
    run_pipeline.main()

    clear_model_cache()

    # --- Part 1: Verify telco_default behavior ---
    telco_model = get_model_for_tenant("telco_default")
    telco_products = pd.read_csv(resolve_path(Path("data") / "processed" / "telco_default" / "products.csv"))
    telco_catalog_ids = set(telco_products["product_id"].astype(str))

    known_telco_customer = str(telco_model.customers_.iloc[0]["customer_id"])

    resp_telco = client.get(
        "/recommendations",
        params={"customer_id": known_telco_customer, "tenant_id": "telco_default", "top_n": 3},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp_telco.status_code == 200
    telco_payload = resp_telco.json()
    assert telco_payload["tenant_id"] == "telco_default"
    assert telco_payload["customer_id"] == known_telco_customer
    assert len(telco_payload["recommendations"]) <= 3

    telco_rec_pids = [r["product_id"] for r in telco_payload["recommendations"]]
    assert len(telco_rec_pids) > 0
    assert set(telco_rec_pids).issubset(telco_catalog_ids)

    expected_direct_recs = telco_model.recommend(known_telco_customer, top_k=3)
    assert telco_rec_pids == expected_direct_recs

    # --- Part 2: Verify fixture_ecommerce behavior ---
    ecom_model = get_model_for_tenant("fixture_ecommerce")
    ecom_products = pd.read_csv(resolve_path(Path("data") / "processed" / "fixture_ecommerce" / "products.csv"))
    ecom_catalog_ids = set(ecom_products["product_id"].astype(str))

    known_ecom_customer = str(ecom_model.customers_.iloc[0]["customer_id"])

    resp_ecom = client.get(
        f"/recommendations/{known_ecom_customer}",
        params={"tenant_id": "fixture_ecommerce", "top_n": 2},
        headers={"X-API-Key": "sk-ecommerce-xxxx"},
    )
    assert resp_ecom.status_code == 200
    ecom_payload = resp_ecom.json()
    assert ecom_payload["tenant_id"] == "fixture_ecommerce"
    assert ecom_payload["customer_id"] == known_ecom_customer

    ecom_rec_pids = [r["product_id"] for r in ecom_payload["recommendations"]]
    assert len(ecom_rec_pids) > 0
    assert set(ecom_rec_pids).issubset(ecom_catalog_ids)
    assert set(ecom_rec_pids).isdisjoint(telco_catalog_ids)

    # --- Part 3: Verify cross-tenant customer query isolation ---
    # Querying fixture_ecommerce with a Telco customer ID must return 404
    resp_cross = client.get(
        "/recommendations",
        params={"customer_id": known_telco_customer, "tenant_id": "fixture_ecommerce"},
        headers={"X-API-Key": "sk-ecommerce-xxxx"},
    )
    assert resp_cross.status_code == 404
    assert resp_cross.json()["detail"] == f"Customer '{known_telco_customer}' not found for tenant 'fixture_ecommerce'"

    # Querying telco_default with an e-commerce customer ID must also return 404
    resp_cross_rev = client.get(
        f"/recommendations/{known_ecom_customer}",
        params={"tenant_id": "telco_default"},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert resp_cross_rev.status_code == 404
    assert resp_cross_rev.json()["detail"] == f"Customer '{known_ecom_customer}' not found for tenant 'telco_default'"
