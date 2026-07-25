from src.evaluation.metrics import evaluate_all, ndcg_at_k, precision_at_k, recall_at_k


def test_precision_at_k_all_hits():
    recommended = ["a", "b", "c"]
    relevant = {"a", "b", "c"}
    assert precision_at_k(recommended, relevant, k=3) == 1.0


def test_precision_at_k_partial_hits():
    recommended = ["a", "x", "c"]
    relevant = {"a", "b", "c"}
    assert precision_at_k(recommended, relevant, k=3) == 2 / 3


def test_recall_at_k():
    recommended = ["a", "x", "c"]
    relevant = {"a", "b", "c"}
    assert recall_at_k(recommended, relevant, k=3) == 2 / 3


def test_ndcg_at_k_perfect_order():
    recommended = ["a", "b", "c"]
    relevant = {"a", "b", "c"}
    assert ndcg_at_k(recommended, relevant, k=3) == 1.0


def test_ndcg_at_k_no_hits():
    recommended = ["x", "y", "z"]
    relevant = {"a", "b", "c"}
    assert ndcg_at_k(recommended, relevant, k=3) == 0.0


def test_evaluate_all_returns_three_metrics():
    result = evaluate_all(["a", "b"], {"a"}, k=2)
    assert set(result.keys()) == {"precision@2", "recall@2", "ndcg@2"}
