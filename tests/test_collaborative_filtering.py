import pandas as pd
import pytest

from src.models.collaborative_filtering import CollaborativeFilteringRecommender


def test_fit_and_recommend_collaborative_filtering():
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c1", "product_id": "p2"},
            {"customer_id": "c2", "product_id": "p1"},
            {"customer_id": "c2", "product_id": "p3"},
            {"customer_id": "c3", "product_id": "p2"},
            {"customer_id": "c3", "product_id": "p3"},
            {"customer_id": "c3", "product_id": "p4"},
            {"customer_id": "c4", "product_id": "p1"},
            {"customer_id": "c4", "product_id": "p4"},
        ]
    )

    model = CollaborativeFilteringRecommender(n_factors=2, random_state=42).fit(interactions)

    # c1 already has p1 and p2; candidate products to recommend are p3, p4
    recs = model.recommend("c1", top_k=2)
    assert isinstance(recs, list)
    assert all(p not in ["p1", "p2"] for p in recs)


def test_score_candidates_consistent_with_recommend():
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c1", "product_id": "p2"},
            {"customer_id": "c2", "product_id": "p1"},
            {"customer_id": "c2", "product_id": "p3"},
            {"customer_id": "c2", "product_id": "p4"},
            {"customer_id": "c3", "product_id": "p2"},
            {"customer_id": "c3", "product_id": "p3"},
            {"customer_id": "c3", "product_id": "p4"},
            {"customer_id": "c4", "product_id": "p1"},
            {"customer_id": "c4", "product_id": "p3"},
            {"customer_id": "c4", "product_id": "p4"},
        ]
    )

    model = CollaborativeFilteringRecommender(n_factors=2, random_state=42).fit(interactions)

    # For c1, unowned products are p3 and p4
    c1_unowned = ["p3", "p4"]
    rec_order = model.recommend("c1", top_k=len(c1_unowned))

    scores = model.score_candidates("c1", c1_unowned)
    assert len(scores) == len(c1_unowned)
    assert all(isinstance(v, float) for v in scores.values())

    # Sorting score_candidates descending must reproduce the exact same order as recommend()
    scored_order = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)
    assert scored_order == rec_order

    # Also test scoring for all products (including owned ones)
    all_products = ["p1", "p2", "p3", "p4"]
    all_scores = model.score_candidates("c1", all_products)
    assert len(all_scores) == 4
    for pid in all_products:
        assert isinstance(all_scores[pid], float)


def test_score_candidates_cold_start_and_unseen_products():
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c1", "product_id": "p2"},
            {"customer_id": "c2", "product_id": "p2"},
        ]
    )

    model = CollaborativeFilteringRecommender(n_factors=2, random_state=42).fit(interactions)

    # Unknown customer returns 0.0 scores
    scores_unknown = model.score_candidates("unknown_customer", ["p1", "p2", "p_unknown"])
    assert scores_unknown == {"p1": 0.0, "p2": 0.0, "p_unknown": 0.0}

    # Known customer with unseen product returns 0.0 for unseen product
    scores_known = model.score_candidates("c1", ["p1", "p_unknown"])
    assert scores_known["p_unknown"] == 0.0
    assert isinstance(scores_known["p1"], float)


def test_score_candidates_unfitted_raises_runtime_error():
    model = CollaborativeFilteringRecommender()
    with pytest.raises(RuntimeError, match=r"Call fit\(\) before score_candidates\(\)"):
        model.score_candidates("c1", ["p1"])
