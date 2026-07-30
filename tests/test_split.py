import pandas as pd

from src.evaluation.split import create_train_test_split


def test_create_train_test_split_holds_out_products_per_customer():
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c1", "product_id": "p2"},
            {"customer_id": "c1", "product_id": "p3"},
            {"customer_id": "c2", "product_id": "p4"},
            {"customer_id": "c2", "product_id": "p5"},
        ]
    )

    train, test = create_train_test_split(interactions, max_test_items_per_customer=2, random_state=42)

    assert len(train) + len(test) == len(interactions)
    assert len(test) == 3
    assert len(train) == 2

    overlap = train.merge(test, on=["customer_id", "product_id"], how="inner")
    assert overlap.empty


def test_create_train_test_split_handles_single_interaction_customers():
    interactions = pd.DataFrame(
        [
            {"customer_id": "c1", "product_id": "p1"},
            {"customer_id": "c2", "product_id": "p2"},
        ]
    )

    train, test = create_train_test_split(interactions, max_test_items_per_customer=2, random_state=7)

    assert len(test) == 2
    assert train.empty
