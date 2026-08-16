import pandas as pd

from src.models.content_based import ContentBasedRecommender


def test_fit_accepts_categorical_feature_columns():
    customers = pd.DataFrame(
        [
            {"customer_id": "c1", "tenure": 12, "MonthlyCharges": 70.0, "Contract": "Month-to-month"},
            {"customer_id": "c2", "tenure": 24, "MonthlyCharges": 90.0, "Contract": "One year"},
        ]
    )
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c2", "product_id": "p2"},
            {"customer_id": "c1", "product_id": "p2"},
        ]
    )

    model = ContentBasedRecommender().fit(customers, interactions, ["tenure", "MonthlyCharges", "Contract"])

    assert model.product_profiles_ is not None
    assert list(model.product_profiles_.index) == ["p1", "p2"]
    recommendations = model.recommend(customers.iloc[0], top_k=2)
    assert set(recommendations) == {"p1", "p2"}


def test_score_candidates_consistent_with_recommend():
    customers = pd.DataFrame(
        [
            {"customer_id": "c1", "tenure": 12, "MonthlyCharges": 70.0, "Contract": "Month-to-month"},
            {"customer_id": "c2", "tenure": 60, "MonthlyCharges": 110.0, "Contract": "Two year"},
            {"customer_id": "c3", "tenure": 3, "MonthlyCharges": 20.0, "Contract": "Month-to-month"},
        ]
    )
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c1", "product_id": "p2"},
            {"customer_id": "c2", "product_id": "p3"},
            {"customer_id": "c3", "product_id": "p4"},
        ]
    )

    model = ContentBasedRecommender().fit(customers, interactions, ["tenure", "MonthlyCharges", "Contract"])

    all_products = ["p1", "p2", "p3", "p4"]
    for _, cust_row in customers.iterrows():
        cid = cust_row["customer_id"]
        rec_order = model.recommend(cust_row, top_k=len(all_products))

        scores = model.score_candidates(cid, all_products)
        assert len(scores) == len(all_products)
        assert all(isinstance(v, float) for v in scores.values())

        # Sorting score_candidates descending should reproduce the same order as recommend()
        scored_order = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)
        assert scored_order == rec_order


def test_score_candidates_cold_start_and_unseen_products():
    customers = pd.DataFrame(
        [
            {"customer_id": "c1", "tenure": 12, "MonthlyCharges": 70.0},
            {"customer_id": "c2", "tenure": 24, "MonthlyCharges": 90.0},
        ]
    )
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c2", "product_id": "p2"},
        ]
    )

    model = ContentBasedRecommender().fit(customers, interactions, ["tenure", "MonthlyCharges"])

    # Unknown customer returns 0.0 scores
    scores_unknown_cust = model.score_candidates("unknown_customer", ["p1", "p2", "p_unknown"])
    assert scores_unknown_cust == {"p1": 0.0, "p2": 0.0, "p_unknown": 0.0}

    # Known customer with unseen product returns 0.0 for unseen product
    scores_known_cust = model.score_candidates("c1", ["p1", "p_unknown"])
    assert scores_known_cust["p_unknown"] == 0.0
    assert isinstance(scores_known_cust["p1"], float)


def test_score_candidates_unfitted_raises_runtime_error():
    import pytest

    model = ContentBasedRecommender()
    with pytest.raises(RuntimeError, match=r"Call fit\(\) before score_candidates\(\)"):
        model.score_candidates("c1", ["p1"])


