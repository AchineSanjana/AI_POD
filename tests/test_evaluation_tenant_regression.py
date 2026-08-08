"""Regression tests confirming split.py and metrics.py tenant_id resolution and identical baseline behavior."""

import pandas as pd
import pytest

from src.evaluation.metrics import (
    evaluate_all,
    evaluate_tenant_customer_recommendations,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from src.evaluation.split import (
    create_train_test_split,
    get_tenant_interactions_path,
    load_tenant_interactions,
)


@pytest.fixture
def sample_interactions_fixture():
    """Standard multi-customer interaction fixture for regression validation."""
    return pd.DataFrame(
        [
            {"customer_id": "cust_1", "product_id": "prod_A"},
            {"customer_id": "cust_1", "product_id": "prod_B"},
            {"customer_id": "cust_1", "product_id": "prod_C"},
            {"customer_id": "cust_2", "product_id": "prod_A"},
            {"customer_id": "cust_2", "product_id": "prod_D"},
            {"customer_id": "cust_3", "product_id": "prod_E"},
        ]
    )


def test_split_regression_identical_on_fixture(sample_interactions_fixture):
    """Confirm create_train_test_split produces identical splits on fixture data before and after tenant_id addition."""
    train_1, test_1 = create_train_test_split(
        sample_interactions_fixture, max_test_items_per_customer=2, random_state=42
    )
    train_2, test_2 = create_train_test_split(
        sample_interactions_fixture, max_test_items_per_customer=2, random_state=42, tenant_id="telco_default"
    )

    pd.testing.assert_frame_equal(train_1, train_2)
    pd.testing.assert_frame_equal(test_1, test_2)

    assert len(train_1) == 2
    assert len(test_1) == 4
    assert set(test_1.loc[test_1["customer_id"] == "cust_3", "product_id"]) == {"prod_E"}


def test_metrics_regression_identical_on_fixture():
    """Confirm metrics produce identical scores before and after tenant_id parameter addition."""
    recommended = ["prod_A", "prod_B", "prod_C", "prod_X", "prod_Y"]
    relevant = {"prod_A", "prod_C", "prod_Z"}

    p = precision_at_k(recommended, relevant, k=5)
    r = recall_at_k(recommended, relevant, k=5)
    n = ndcg_at_k(recommended, relevant, k=5)

    all_metrics_default = evaluate_all(recommended, relevant, k=5)
    all_metrics_tenant = evaluate_all(recommended, relevant, k=5, tenant_id="telco_default")

    assert p == 2 / 5
    assert r == 2 / 3
    assert all_metrics_default == all_metrics_tenant
    assert all_metrics_tenant["precision@5"] == p
    assert all_metrics_tenant["recall@5"] == r
    assert all_metrics_tenant["ndcg@5"] == n


def test_split_resolves_tenant_processed_paths():
    """Verify split.py resolves processed paths for both telco_default and movielens_demo."""
    telco_path = get_tenant_interactions_path("telco_default")
    movie_path = get_tenant_interactions_path("movielens_demo")

    assert telco_path.name == "interactions.csv"
    assert "telco_default" in str(telco_path)
    assert movie_path.name == "interactions.csv"
    assert "movielens_demo" in str(movie_path)

    # Load via tenant_id
    if telco_path.exists():
        telco_interactions = load_tenant_interactions("telco_default")
        assert "customer_id" in telco_interactions.columns
        assert "product_id" in telco_interactions.columns

        train, test = create_train_test_split(tenant_id="telco_default", max_test_items_per_customer=2, random_state=42)
        assert len(train) > 0
        assert len(test) > 0
        assert "customer_id" in train.columns
        assert "product_id" in train.columns


def test_evaluate_tenant_customer_recommendations():
    """Verify evaluate_tenant_customer_recommendations evaluates batch predictions against tenant interactions."""
    test_df = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c1", "product_id": "p2"},
            {"customer_id": "c2", "product_id": "p3"},
        ]
    )
    recs = {
        "c1": ["p1", "p2", "p9"],
        "c2": ["p3", "p4", "p5"],
    }

    scores = evaluate_tenant_customer_recommendations(
        recommendations_by_customer=recs,
        test_interactions=test_df,
        tenant_id="telco_default",
        k=3,
    )

    assert "precision@3" in scores
    assert "recall@3" in scores
    assert "ndcg@3" in scores
    assert scores["recall@3"] == 1.0
