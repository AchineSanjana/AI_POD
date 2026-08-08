"""End-to-end multi-tenant regression test running full pipeline (ingest -> train -> evaluate -> persist -> serve)

Runs both 'telco_default' and the new 'movielens_demo' tenant in sequence within a single test to guarantee
that multi-tenant generalization and serving contracts cannot silently regress.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from scripts import run_pipeline
from src.api.app import app
from src.api.recommendations import (
    _recommend_for_customer,
    clear_model_cache,
    get_model_for_tenant,
)
from src.utils.config import resolve_path

client = TestClient(app)


def test_e2e_multitenant_pipeline_and_serving(monkeypatch):
    """End-to-end test executing full pipeline for both tenants in sequence and asserting serving via API."""
    tenants = ["telco_default", "movielens_demo"]
    api_keys = {
        "telco_default": "sk-telco-xxxx",
        "movielens_demo": "sk-movielens-xxxx",
    }

    # -------------------------------------------------------------------------
    # 1. Execute full pipeline sequentially for both tenants
    # -------------------------------------------------------------------------
    for tenant_id in tenants:
        monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--tenant_id", tenant_id])
        run_pipeline.main()

    # Clear memory cache so API layer loads fresh model artifacts from disk
    clear_model_cache()

    # -------------------------------------------------------------------------
    # 2. Verify processed datasets and loadable final_model.joblib for each tenant
    # -------------------------------------------------------------------------
    tenant_catalogs: dict[str, set[str]] = {}
    known_customers: dict[str, str] = {}

    for tenant_id in tenants:
        proc_dir = resolve_path(Path("data") / "processed" / tenant_id)
        model_dir = resolve_path(Path("models") / tenant_id)
        model_path = model_dir / "final_model.joblib"

        # Assert data artifacts exist and are non-empty
        assert (proc_dir / "customers.csv").exists(), f"Missing customers.csv for {tenant_id}"
        assert (proc_dir / "products.csv").exists(), f"Missing products.csv for {tenant_id}"
        assert (proc_dir / "interactions.csv").exists(), f"Missing interactions.csv for {tenant_id}"

        customers_df = pd.read_csv(proc_dir / "customers.csv")
        products_df = pd.read_csv(proc_dir / "products.csv")
        interactions_df = pd.read_csv(proc_dir / "interactions.csv")

        assert len(customers_df) > 0, f"Empty customers for {tenant_id}"
        assert len(products_df) > 0, f"Empty products for {tenant_id}"
        assert len(interactions_df) > 0, f"Empty interactions for {tenant_id}"

        # Assert model artifact exists, loads properly, and exposes recommendation capability
        assert model_path.exists(), f"Missing final_model.joblib for {tenant_id}"
        loaded_model = joblib.load(model_path)
        assert hasattr(loaded_model, "recommend"), f"Model for {tenant_id} missing recommend method"

        tenant_catalogs[tenant_id] = set(products_df["product_id"].astype(str))
        known_customers[tenant_id] = str(customers_df.iloc[0]["customer_id"])

    # -------------------------------------------------------------------------
    # 3. Direct API layer recommendation verification (calling actual serving code paths)
    # -------------------------------------------------------------------------
    for tenant_id in tenants:
        customer_id = known_customers[tenant_id]
        catalog = tenant_catalogs[tenant_id]
        api_key = api_keys[tenant_id]

        # A. Direct internal API function: _recommend_for_customer
        direct_recs = _recommend_for_customer(tenant_id=tenant_id, customer_id=customer_id, top_n=5)
        assert isinstance(direct_recs, list)
        assert len(direct_recs) > 0, f"Expected non-empty direct recs for {tenant_id}"

        for rec in direct_recs:
            assert "rank" in rec
            assert "product_id" in rec
            assert str(rec["product_id"]) in catalog, f"Product {rec['product_id']} not in {tenant_id} catalog"

        # B. HTTP endpoint serving via FastAPI TestClient with X-API-Key auth
        response = client.get(
            "/recommendations",
            params={"customer_id": customer_id, "tenant_id": tenant_id, "top_n": 5},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200, f"API error for {tenant_id}: {response.text}"
        payload = response.json()

        assert payload["tenant_id"] == tenant_id
        assert str(payload["customer_id"]) == str(customer_id)
        assert len(payload["recommendations"]) > 0, f"API returned empty recommendations for {tenant_id}"

        api_pids = [r["product_id"] for r in payload["recommendations"]]
        assert set(api_pids).issubset(catalog), f"API recs violated catalog scope for {tenant_id}"

    # -------------------------------------------------------------------------
    # 4. Assert strict cross-tenant catalog and customer isolation
    # -------------------------------------------------------------------------
    assert tenant_catalogs["telco_default"].isdisjoint(
        tenant_catalogs["movielens_demo"]
    ), "Cross-contamination: catalogs overlap between tenants"

    # Cross-tenant query should fail with 404
    resp_cross = client.get(
        "/recommendations",
        params={"customer_id": known_customers["telco_default"], "tenant_id": "movielens_demo"},
        headers={"X-API-Key": api_keys["movielens_demo"]},
    )
    assert resp_cross.status_code == 404
