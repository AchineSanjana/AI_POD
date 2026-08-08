"""CLI entry point: loads raw data for a given tenant, builds recommendation tables,
trains & evaluates all models, and saves the winning model artifact.

Usage:
    python scripts/run_pipeline.py --tenant_id telco_default
    python scripts/run_pipeline.py --tenant_id fixture_ecommerce
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Allow running as `python scripts/run_pipeline.py` from the project root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# pyrefly: ignore [missing-import]
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
# pyrefly: ignore [missing-import]
from src.evaluation.metrics import evaluate_all
# pyrefly: ignore [missing-import]
from src.evaluation.split import create_train_test_split
# pyrefly: ignore [missing-import]
from src.models.collaborative_filtering import CollaborativeFilteringRecommender
# pyrefly: ignore [missing-import]
from src.models.content_based import ContentBasedRecommender
# pyrefly: ignore [missing-import]
from src.models.hybrid import HybridRecommender
# pyrefly: ignore [missing-import]
from src.models.ranking_model import LearnedRankingRecommender
# pyrefly: ignore [missing-import]
from src.utils.config import TenantConfig, get_tenant_config, load_config, resolve_path
# pyrefly: ignore [missing-import]
from src.utils.logger import get_logger
# pyrefly: ignore [missing-import]
from src.utils.persistence import save_model

logger = get_logger(__name__)


def evaluate_models(
    customers: pd.DataFrame,
    products: pd.DataFrame,
    interactions: pd.DataFrame,
    tenant_cfg: TenantConfig,
) -> tuple[dict[str, dict[str, float]], str, Any]:
    """Train and evaluate content-based, collaborative, hybrid, and ranking models on tenant data."""
    feature_columns = [f.name for f in tenant_cfg.customers.features]
    train_interactions, test_interactions = create_train_test_split(
        interactions, max_test_items_per_customer=2, random_state=42
    )

    customer_lookup = customers.set_index("customer_id")
    customer_ids = sorted(test_interactions["customer_id"].drop_duplicates())
    if len(customer_ids) > 100:
        customer_ids = customer_ids[:100]

    content_model = ContentBasedRecommender().fit(customers, train_interactions, feature_columns)
    cf_model = CollaborativeFilteringRecommender(n_factors=5).fit(train_interactions)
    hybrid_model = HybridRecommender().fit(customers, train_interactions, feature_columns)
    ranking_model = LearnedRankingRecommender(customer_specs=tenant_cfg.customers.features).fit(
        customers, train_interactions, products
    )

    metrics_by_model: dict[str, list[dict[str, float]]] = {
        "content_based": [],
        "collaborative": [],
        "hybrid": [],
        "ranking": [],
    }

    for customer_id in customer_ids:
        relevant = set(
            test_interactions.loc[test_interactions["customer_id"] == customer_id, "product_id"]
        )
        if not relevant:
            continue

        customer_row = customer_lookup.loc[customer_id]

        cb_recs = content_model.recommend(customer_row, top_k=5)
        cf_recs = cf_model.recommend(customer_id, top_k=5)
        hy_recs = hybrid_model.recommend(customer_id, customer_row, top_k=5)
        rk_recs = ranking_model.recommend(customer_id, top_k=5)

        metrics_by_model["content_based"].append(evaluate_all(cb_recs, relevant, k=5))
        metrics_by_model["collaborative"].append(evaluate_all(cf_recs, relevant, k=5))
        metrics_by_model["hybrid"].append(evaluate_all(hy_recs, relevant, k=5))
        metrics_by_model["ranking"].append(evaluate_all(rk_recs, relevant, k=5))

    scores: dict[str, dict[str, float]] = {}
    for name, rows in metrics_by_model.items():
        if rows:
            scores[name] = {
                m: sum(r[m] for r in rows) / len(rows)
                for m in ["precision@5", "recall@5", "ndcg@5"]
            }
        else:
            scores[name] = {"precision@5": 0.0, "recall@5": 0.0, "ndcg@5": 0.0}

    winning_name = max(scores.keys(), key=lambda k: scores[k]["ndcg@5"])

    # Fit winning model on full tenant dataset
    if winning_name == "content_based":
        winning_model = ContentBasedRecommender().fit(customers, interactions, feature_columns)
    elif winning_name == "collaborative":
        winning_model = CollaborativeFilteringRecommender(n_factors=5).fit(interactions)
    elif winning_name == "hybrid":
        winning_model = HybridRecommender().fit(customers, interactions, feature_columns)
    else:
        winning_model = LearnedRankingRecommender(customer_specs=tenant_cfg.customers.features).fit(
            customers, interactions, products
        )

    winning_model.customers_ = customers
    winning_model.products_ = products

    return scores, winning_name, winning_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Recommendation Pipeline for a specific tenant.")
    parser.add_argument(
        "--tenant_id",
        type=str,
        default="telco_default",
        help="Tenant ID to run pipeline for (default: telco_default)",
    )
    args = parser.parse_args()

    config = load_config()
    tenant_cfg = get_tenant_config(config, args.tenant_id)
    adapter = GenericConfigAdapter(tenant_cfg)

    logger.info(f"Starting data pipeline for tenant '{args.tenant_id}'...")
    customers, products, interactions = adapter.run()

    # Write processed data to tenant-isolated directory: data/processed/{tenant_id}/
    out_dir = resolve_path(Path("data") / "processed" / args.tenant_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    customers.to_csv(out_dir / "customers.csv", index=False)
    products.to_csv(out_dir / "products.csv", index=False)
    interactions.to_csv(out_dir / "interactions.csv", index=False)

    logger.info(f"Wrote tenant '{args.tenant_id}' tables to {out_dir}")

    # Evaluate models and select winning model
    scores, winning_name, winning_model = evaluate_models(customers, products, interactions, tenant_cfg)
    logger.info(f"Tenant '{args.tenant_id}' evaluation complete. Scores: {scores}")
    logger.info(f"Winning model for tenant '{args.tenant_id}': {winning_name}")

    # Save winning model to models/{tenant_id}/final_model.joblib
    model_dir = resolve_path(Path("models") / args.tenant_id)
    model_dir.mkdir(parents=True, exist_ok=True)
    saved_path = save_model(winning_model, model_dir / "final_model.joblib")
    logger.info(f"Saved winning model for tenant '{args.tenant_id}' to {saved_path}")


if __name__ == "__main__":
    main()
