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
