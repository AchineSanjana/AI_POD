"""Integration test demonstrating generalization to a second distinct tenant (fixture_ecommerce)."""

import pandas as pd
import pytest

# pyrefly: ignore [missing-import]
from src.core.schema import CustomerSchema, InteractionSchema, ProductSchema
# pyrefly: ignore [missing-import]
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
# pyrefly: ignore [missing-import]
from src.models.content_based import ContentBasedRecommender
# pyrefly: ignore [missing-import]
from src.models.ranking_model import LearnedRankingRecommender
# pyrefly: ignore [missing-import]
from src.utils.config import get_tenant_config, load_config


def test_generic_adapter_second_tenant_generalization():
    """Verify GenericConfigAdapter and recommendation models generalize to fixture_ecommerce."""
    cfg = load_config()

    # 1. Load second tenant config and run GenericConfigAdapter
    tenant_cfg = get_tenant_config(cfg, "fixture_ecommerce")
    adapter = GenericConfigAdapter(tenant_cfg)
    customers, products, interactions = adapter.run()

    # 2. Assert output DataFrames validate against schemas
    assert isinstance(customers, pd.DataFrame)
    assert isinstance(products, pd.DataFrame)
    assert isinstance(interactions, pd.DataFrame)

    adapter.customer_schema.validate_values(customers)
    adapter.product_schema.validate_values(products)
    adapter.interaction_schema.validate(interactions)

    assert "customer_id" in customers.columns
    assert "signup_days" in customers.columns
    assert "monthly_spend" in customers.columns
    assert "plan_type" in customers.columns
    assert len(customers) == 10

    # 3. Train ContentBasedRecommender with zero code changes
    feature_cols = [f.name for f in tenant_cfg.customers.features]
    cb_model = ContentBasedRecommender()
    cb_model.fit(customers=customers, interactions=interactions, feature_columns=feature_cols)

    sample_customer_id = str(customers.iloc[0]["customer_id"])
    sample_customer_row = customers.iloc[0]

    cb_recs = cb_model.recommend(customer_features=sample_customer_row, top_k=2)
    assert isinstance(cb_recs, list)
    assert len(cb_recs) > 0
    assert all(isinstance(pid, str) for pid in cb_recs)

    # 4. Train LearnedRankingRecommender with zero code changes
    ranking_model = LearnedRankingRecommender(customer_specs=tenant_cfg.customers.features)
    ranking_model.fit(customers=customers, interactions=interactions, products=products)

    rank_recs = ranking_model.recommend(customer_id=sample_customer_id, top_k=2)
    assert isinstance(rank_recs, list)
    assert len(rank_recs) > 0
    assert all(isinstance(pid, str) for pid in rank_recs)
