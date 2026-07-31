from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.collaborative_filtering import CollaborativeFilteringRecommender
from src.models.content_based import ContentBasedRecommender
from src.models.hybrid import HybridRecommender
from src.models.ranking_model import LearnedRankingRecommender
from src.evaluation.metrics import evaluate_all
from src.evaluation.split import create_train_test_split


DATA_DIR = ROOT / "data" / "processed"
REPORT_PATH = ROOT / "docs" / "model_evaluation_report.md"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    customers = pd.read_csv(DATA_DIR / "customers.csv")
    interactions = pd.read_csv(DATA_DIR / "interactions.csv")
    products = pd.read_csv(DATA_DIR / "products.csv")

    if "customerID" in customers.columns:
        customers = customers.rename(columns={"customerID": "customer_id"})

    return customers, interactions, products


def build_report() -> str:
    customers, interactions, products = load_data()
    feature_columns = ["tenure", "MonthlyCharges", "Contract"]
    train_interactions, test_interactions = create_train_test_split(
        interactions, max_test_items_per_customer=2, random_state=42
    )

    customer_lookup = customers.set_index("customer_id")
    customer_ids = sorted(test_interactions["customer_id"].drop_duplicates())

    metrics_by_model: dict[str, list[dict[str, float]]] = {
        "content_based": [],
        "collaborative": [],
        "hybrid": [],
        "ranking": [],
    }

    content_model = ContentBasedRecommender().fit(customers, train_interactions, feature_columns)
    cf_model = CollaborativeFilteringRecommender(n_factors=5).fit(train_interactions)
    hybrid_model = HybridRecommender().fit(customers, train_interactions, feature_columns)
    ranking_model = LearnedRankingRecommender().fit(customers, train_interactions, products)

    for customer_id in customer_ids:
        relevant = set(
            test_interactions.loc[test_interactions["customer_id"] == customer_id, "product_id"]
        )
        if not relevant:
            continue

        customer_row = customer_lookup.loc[customer_id]

        content_recs = content_model.recommend(customer_row, top_k=5)
        cf_recs = cf_model.recommend(customer_id, top_k=5)
        hybrid_recs = hybrid_model.recommend(customer_id, customer_row, top_k=5)
        ranking_recs = ranking_model.recommend(customer_id, top_k=5)

        metrics_by_model["content_based"].append(
            evaluate_all(content_recs, relevant, k=5)
        )
        metrics_by_model["collaborative"].append(
            evaluate_all(cf_recs, relevant, k=5)
        )
        metrics_by_model["hybrid"].append(
            evaluate_all(hybrid_recs, relevant, k=5)
        )
        metrics_by_model["ranking"].append(
            evaluate_all(ranking_recs, relevant, k=5)
        )

    def summarize(rows: list[dict[str, float]]) -> dict[str, float]:
        if not rows:
            return {k: 0.0 for k in ["precision@5", "recall@5", "ndcg@5"]}
        return {
            metric: sum(item[metric] for item in rows) / len(rows)
            for metric in ["precision@5", "recall@5", "ndcg@5"]
        }

    summaries = {name: summarize(rows) for name, rows in metrics_by_model.items()}

    def segment_key(customer_id: str) -> str:
        train_count = int(
            (train_interactions[train_interactions["customer_id"] == customer_id]).shape[0]
        )
        if train_count <= 2:
            return "newer"
        return "established"

    segment_metrics: dict[str, dict[str, list[dict[str, float]]]] = {}
    for segment in ["newer", "established"]:
        segment_metrics[segment] = {model_name: [] for model_name in metrics_by_model}

    for customer_id in customer_ids:
        segment = segment_key(customer_id)
        relevant = set(
            test_interactions.loc[test_interactions["customer_id"] == customer_id, "product_id"]
        )
        customer_row = customer_lookup.loc[customer_id]

        content_recs = content_model.recommend(customer_row, top_k=5)
        cf_recs = cf_model.recommend(customer_id, top_k=5)
        hybrid_recs = hybrid_model.recommend(customer_id, customer_row, top_k=5)
        ranking_recs = ranking_model.recommend(customer_id, top_k=5)

        for model_name, recs in {
            "content_based": content_recs,
            "collaborative": cf_recs,
            "hybrid": hybrid_recs,
            "ranking": ranking_recs,
        }.items():
            segment_metrics[segment][model_name].append(
                evaluate_all(recs, relevant, k=5)
            )

    segment_summaries = {
        segment: {name: summarize(rows) for name, rows in values.items()}
        for segment, values in segment_metrics.items()
    }

    def pick_winner(values: dict[str, dict[str, float]]) -> str:
        return max(values, key=lambda name: values[name]["ndcg@5"])

    overall_winner = pick_winner(summaries)
    segment_winners = {segment: pick_winner(values) for segment, values in segment_summaries.items()}

    lines = []
    lines.append("# Model evaluation report")
    lines.append("")
    lines.append(f"- Data: {DATA_DIR}")
    lines.append(f"- Train/test split: {len(train_interactions)} training rows, {len(test_interactions)} held-out rows")
    lines.append(f"- Customers evaluated: {len(customer_ids)}")
    lines.append(f"- Feature columns used for content/hybrid: {', '.join(feature_columns)}")
    lines.append("")
    lines.append("## Overall comparison")
    lines.append("")
    lines.append("| Model | Precision@5 | Recall@5 | NDCG@5 |")
    lines.append("| --- | ---: | ---: | ---: |")
    for name, metrics in summaries.items():
        lines.append(
            f"| {name} | {metrics['precision@5']:.3f} | {metrics['recall@5']:.3f} | {metrics['ndcg@5']:.3f} |"
        )
    lines.append("")
    lines.append(f"**Winner (by NDCG@5):** {overall_winner}")
    lines.append("")
    lines.append("## Segment analysis")
    lines.append("")
    lines.append("| Segment | Content-based | Collaborative | Hybrid | Ranking | Winner |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for segment in ["newer", "established"]:
        segment_row = segment_summaries[segment]
        winner = segment_winners[segment]
        lines.append(
            f"| {segment} | P={segment_row['content_based']['precision@5']:.3f}/R={segment_row['content_based']['recall@5']:.3f}/N={segment_row['content_based']['ndcg@5']:.3f} | P={segment_row['collaborative']['precision@5']:.3f}/R={segment_row['collaborative']['recall@5']:.3f}/N={segment_row['collaborative']['ndcg@5']:.3f} | P={segment_row['hybrid']['precision@5']:.3f}/R={segment_row['hybrid']['recall@5']:.3f}/N={segment_row['hybrid']['ndcg@5']:.3f} | P={segment_row['ranking']['precision@5']:.3f}/R={segment_row['ranking']['recall@5']:.3f}/N={segment_row['ranking']['ndcg@5']:.3f} | {winner} |"
        )
    lines.append("")
    lines.append("## Simple chart")
    lines.append("")
    lines.append("```mermaid")
    lines.append("xychart-beta")
    lines.append("    title Model comparison (NDCG@5)")
    lines.append("    x-axis [content_based, collaborative, hybrid, ranking]")
    lines.append("    y-axis " + "0 to 1")
    lines.append("    bar [" + ", ".join(f"{summaries[name]['ndcg@5']:.3f}" for name in ["content_based", "collaborative", "hybrid", "ranking"]) + "]")
    lines.append("```")
    lines.append("")
    lines.append("## Takeaway")
    lines.append("")
    lines.append(
        "The report highlights whether a hybrid blend is strongest overall and whether the lead shifts by customer history."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = build_report()
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote evaluation report to {REPORT_PATH}")
