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


def test_stacked_ranking_model_includes_submodel_features():
    import pytest
    from src.models.collaborative_filtering import CollaborativeFilteringRecommender
    from src.models.content_based import ContentBasedRecommender

    customers = pd.DataFrame(
        [
            {"customer_id": "c1", "tenure": 12, "MonthlyCharges": 70.0, "Contract": "Month-to-month"},
            {"customer_id": "c2", "tenure": 24, "MonthlyCharges": 90.0, "Contract": "One year"},
            {"customer_id": "c3", "tenure": 36, "MonthlyCharges": 110.0, "Contract": "Two year"},
        ]
    )
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c1", "product_id": "p2"},
            {"customer_id": "c2", "product_id": "p2"},
            {"customer_id": "c2", "product_id": "p3"},
            {"customer_id": "c3", "product_id": "p1"},
            {"customer_id": "c3", "product_id": "p3"},
        ]
    )
    products = pd.DataFrame(
        [
            {"product_id": "p1", "category": "Core"},
            {"product_id": "p2", "category": "Add-on"},
            {"product_id": "p3", "category": "Add-on"},
        ]
    )

    # 1. Test error when unfitted submodels are passed
    unfitted_cb = ContentBasedRecommender()
    unfitted_cf = CollaborativeFilteringRecommender()
    with pytest.raises(ValueError, match="content_model.*must be fitted"):
        LearnedRankingRecommender(content_model=unfitted_cb).fit(customers, interactions, products)

    # Fit submodels
    cb_model = ContentBasedRecommender().fit(customers, interactions, ["tenure", "MonthlyCharges", "Contract"])
    with pytest.raises(ValueError, match="cf_model.*must be fitted"):
        LearnedRankingRecommender(content_model=cb_model, cf_model=unfitted_cf).fit(customers, interactions, products)

    cf_model = CollaborativeFilteringRecommender(n_factors=2, random_state=42).fit(interactions)

    # 2. Fit stacked ranking model
    stacked_model = LearnedRankingRecommender(
        content_model=cb_model,
        cf_model=cf_model,
        n_estimators=10,
    ).fit(customers, interactions, products)

    # 3. Assert stacked features exist in feature_columns_
    assert "content_based_score" in stacked_model.feature_columns_
    assert "collaborative_score" in stacked_model.feature_columns_

    # 4. Check recommendation generation
    recs = stacked_model.recommend("c1", top_k=2)
    assert isinstance(recs, list)
    assert recs == ["p3"]  # c1 already has p1 and p2, only p3 is candidate

