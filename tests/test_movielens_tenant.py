"""End-to-end integration test verifying MovieLens Latest-Small tenant ingestion, training, and recommendation API."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from scripts import run_pipeline
from src.api.app import app
from src.api.recommendations import clear_model_cache, get_model_for_tenant
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
from src.models.collaborative_filtering import CollaborativeFilteringRecommender
from src.models.content_based import ContentBasedRecommender
from src.models.ranking_model import LearnedRankingRecommender
from src.utils.config import get_tenant_config, load_config, resolve_path

client = TestClient(app)


def test_movielens_adapter_and_schemas():
    """Verify GenericConfigAdapter processes MovieLens Latest-Small and validates schemas."""
    cfg = load_config()
    tenant_cfg = get_tenant_config(cfg, "movielens_small")
    adapter = GenericConfigAdapter(tenant_cfg)
    customers, products, interactions = adapter.run()

    assert isinstance(customers, pd.DataFrame)
    assert isinstance(products, pd.DataFrame)
    assert isinstance(interactions, pd.DataFrame)

    assert len(customers) >= 600
    assert "customer_id" in customers.columns
    assert "rating_count" in customers.columns
    assert "avg_rating" in customers.columns
    assert "favorite_genre" in customers.columns

    assert len(products) > 0
    assert "product_id" in products.columns
    assert "product_name" in products.columns

    assert len(interactions) > 0
    assert "customer_id" in interactions.columns
    assert "product_id" in interactions.columns

    adapter.customer_schema.validate(customers)
    adapter.product_schema.validate(products)
    adapter.interaction_schema.validate(interactions)


def test_movielens_pipeline_and_api(monkeypatch):
    """Verify run_pipeline builds isolated MovieLens models and API endpoint serves recommendations."""
    # 1. Run pipeline for movielens_demo
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--tenant_id", "movielens_demo"])
    run_pipeline.main()

    clear_model_cache()

    # 2. Verify artifact files exist
    proc_dir = resolve_path(Path("data") / "processed" / "movielens_demo")
    model_dir = resolve_path(Path("models") / "movielens_demo")

    assert (proc_dir / "customers.csv").exists()
    assert (proc_dir / "products.csv").exists()
    assert (proc_dir / "interactions.csv").exists()
    assert (model_dir / "final_model.joblib").exists()

    # 3. Test API recommendations for a known MovieLens user
    ml_model = get_model_for_tenant("movielens_demo")
    proc_customers = pd.read_csv(proc_dir / "customers.csv")
    known_user = str(proc_customers.iloc[0]["customer_id"])

    resp = client.get(
        "/recommendations",
        params={"customer_id": known_user, "tenant_id": "movielens_demo", "top_n": 3},
        headers={"X-API-Key": "sk-movielens-xxxx"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["tenant_id"] == "movielens_demo"
    assert payload["customer_id"] == known_user
    assert len(payload["recommendations"]) <= 3

    pids = [r["product_id"] for r in payload["recommendations"]]
    assert len(pids) > 0

    # 4. Cross-tenant customer isolation
    resp_cross = client.get(
        "/recommendations",
        params={"customer_id": "non_existent_customer_99999", "tenant_id": "movielens_demo"},
        headers={"X-API-Key": "sk-movielens-xxxx"},
    )
    assert resp_cross.status_code == 404
