import pandas as pd

from src.models.ranking_model import LearnedRankingRecommender


def test_ranking_model_returns_candidates_for_known_customer():
    customers = pd.DataFrame(
        [
            {"customer_id": "c1", "tenure": 12, "MonthlyCharges": 70.0, "SeniorCitizen": 0, "Contract": "Month-to-month"},
            {"customer_id": "c2", "tenure": 24, "MonthlyCharges": 90.0, "SeniorCitizen": 0, "Contract": "One year"},
        ]
    )
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c2", "product_id": "p2"},
        ]
    )
    products = pd.DataFrame(
        [
            {"product_id": "p1", "category": "Core"},
            {"product_id": "p2", "category": "Add-on"},
            {"product_id": "p3", "category": "Add-on"},
        ]
    )

    model = LearnedRankingRecommender().fit(customers, interactions, products)
    recommendations = model.recommend("c1", top_k=2)

    assert recommendations
    assert set(recommendations).issubset({"p2", "p3"})


def test_ranking_model_returns_empty_for_unknown_customer():
    customers = pd.DataFrame(
        [{"customer_id": "c1", "tenure": 12, "MonthlyCharges": 70.0, "SeniorCitizen": 0, "Contract": "Month-to-month"}]
    )
    interactions = pd.DataFrame([{"customer_id": "c1", "product_id": "p1"}])
    products = pd.DataFrame([
        {"product_id": "p1", "category": "Core"},
        {"product_id": "p2", "category": "Add-on"},
    ])

    model = LearnedRankingRecommender().fit(customers, interactions, products)
    assert model.recommend("missing-customer", top_k=2) == []
