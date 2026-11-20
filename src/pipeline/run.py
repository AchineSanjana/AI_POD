"""Reusable tenant recommendation training pipeline and model tournament."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import logging
from typing import Any

import pandas as pd

from src.api.recommendations import clear_model_cache
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
from src.evaluation.metrics import evaluate_all
from src.evaluation.split import create_train_test_split
from src.models.collaborative_filtering import CollaborativeFilteringRecommender
from src.models.content_based import ContentBasedRecommender
from src.models.hybrid import HybridRecommender
from src.models.ranking_model import LearnedRankingRecommender
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import get_tenant_config, load_config
from src.utils.persistence import load_model, save_model

logger = logging.getLogger(__name__)

MODEL_KEYS = ["content", "collaborative", "hybrid", "xgboost"]
DISPLAY_NAMES = {
    "content": "Content-Based",
    "collaborative": "Collaborative Filtering",
    "hybrid": "Dynamic Hybrid",
    "xgboost": "Learned Ranking (XGBoost)",
}


def run_tenant_pipeline(
    tenant_id: str,
    storage: StorageBackend | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Train candidate recommenders, select winner via NDCG@5, refit on full data, and persist.

    Args:
        tenant_id: Tenant identifier.
        storage: Configured StorageBackend (LocalStorage or S3Storage).
        progress_callback: Optional callable accepting status dictionary at each stage.
        config: Loaded config dictionary.

    Returns:
        dict[str, Any]: Final status dictionary containing metrics, winner, and model path.
    """
    if config is None:
        config = load_config()
    if storage is None:
        storage = get_storage_backend(config)

    tenant_cfg = get_tenant_config(config, tenant_id)
    started_at = datetime.now(timezone.utc).isoformat()

    models_state: dict[str, str] = {k: "queued" for k in MODEL_KEYS}
    metrics_state: dict[str, dict[str, float]] = {}
    current_dataset: dict[str, Any] = {}
    current_winner_key: str | None = None
    current_winner_model: str | None = None
    current_model_path: str | None = None
    current_trained_count: int | None = None
    current_trained_at: str | None = None
    products_added_from_interactions: int = 0

    def update_progress(
        stage: str,
        message: str,
        status_val: str = "running",
        error: str | None = None,
        ready: bool = False,
    ) -> dict[str, Any]:
        nonlocal current_winner_key, current_winner_model, current_model_path, current_trained_count, current_trained_at, products_added_from_interactions
        now_iso = datetime.now(timezone.utc).isoformat()
        state = {
            "tenant_id": tenant_id,
            "status": status_val,
            "ready": ready,
            "status_url": "/v1/onboard/status",
            "stage": stage,
            "message": message,
            "models": dict(models_state),
            "metrics": dict(metrics_state),
            "winner_model": current_winner_model,
            "winner_key": current_winner_key,
            "dataset": dict(current_dataset),
            "started_at": started_at,
            "updated_at": now_iso,
            "model_path": current_model_path,
            "error": error,
            "trained_product_ids_count": current_trained_count,
            "trained_at": current_trained_at,
            "products_added_from_interactions": products_added_from_interactions,
        }

        try:
            status_bytes = json.dumps(state, indent=2).encode("utf-8")
            storage.write_file(f"status/{tenant_id}.json", status_bytes)
        except Exception as e:
            logger.warning("[%s] Failed to write status file to storage: %s", tenant_id, e)

        if progress_callback:
            try:
                progress_callback(state)
            except Exception as e:
                logger.warning("[%s] Progress callback failed: %s", tenant_id, e)

        log_level = logging.ERROR if status_val == "failed" else logging.INFO
        logger.log(log_level, "[%s] [%s] %s", tenant_id, stage, message)
        return state

    try:
        # Stage 1: Starting & Data Adaptation
        update_progress("starting", f"Starting data pipeline for tenant '{tenant_id}'...")
        update_progress(
            "adapting_data",
            f"Adapting raw dataset and generating tables for tenant '{tenant_id}'...",
        )
        adapter = GenericConfigAdapter(tenant_cfg, storage=storage)
        customers, products, interactions = adapter.run()

        # Check for tenant-managed catalogue (Step C2 integration)
        cat_path = f"data/catalog/{tenant_id}/catalog.csv"
        if storage.exists(cat_path):
            logger.info("[%s] Found managed catalog '%s'. Using catalog as authoritative source of truth.", tenant_id, cat_path)
            from src.catalog.service import load_catalog, save_catalog, ConcurrentModificationError

            # 3b: Products in interaction data missing from catalogue are ADDED as status=active, in_stock=1
            interaction_pids = set(interactions["product_id"].dropna().astype(str).str.strip()) - {"", "nan", "None"}
            for attempt in range(2):
                try:
                    cat_df, cat_ver = load_catalog(tenant_id, storage=storage, auto_seed=False)
                    current_cat_pids = set(cat_df["product_id"].astype(str).str.strip()) if not cat_df.empty else set()
                    missing_pids = sorted(interaction_pids - current_cat_pids)
                    if missing_pids:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        new_rows = []
                        for m_pid in missing_pids:
                            new_rows.append({
                                "product_id": m_pid,
                                "product_name": m_pid,
                                "category": "General",
                                "status": "active",
                                "in_stock": 1,
                                "created_at": now_iso,
                                "updated_at": now_iso,
                            })
                        updated_cat_df = pd.concat([cat_df, pd.DataFrame(new_rows)], ignore_index=True)
                        save_catalog(
                            tenant_id=tenant_id,
                            df=updated_cat_df,
                            expected_version=cat_ver,
                            who="pipeline",
                            action="interaction_sync",
                            product_ids=missing_pids,
                            storage=storage,
                        )
                        products_added_from_interactions = len(missing_pids)
                        logger.info("[%s] Added %d missing interaction products to catalogue.", tenant_id, products_added_from_interactions)
                        cat_df = updated_cat_df
                    break
                except ConcurrentModificationError:
                    if attempt == 1:
                        logger.warning("[%s] Concurrency conflict syncing interaction products; proceeding with current catalog.", tenant_id)
                        cat_df, _ = load_catalog(tenant_id, storage=storage, auto_seed=False)
                    else:
                        time.sleep(0.1)

            # 3e: If active set is empty or has fewer than 2 products, fail training with a clear error
            active_mask = cat_df["status"].astype(str).str.lower().str.strip() == "active"
            active_cat_df = cat_df[active_mask].copy()
            if len(active_cat_df) < 2:
                err_msg = (
                    f"Catalogue for tenant '{tenant_id}' has fewer than 2 active products "
                    f"({len(active_cat_df)} active). At least 2 active products are required for model training."
                )
                update_progress(
                    stage="failed",
                    message=f"Training failed: {err_msg}",
                    status_val="failed",
                    error=err_msg,
                    ready=False,
                )
                raise ValueError(err_msg)

            # 3c & 3d: Build products DataFrame from catalogue's active products
            # Declared ProductSchema features feed content-based features; undeclared columns are omitted.
            product_schema_cols = {"product_id", "product_name", "category"}
            if hasattr(tenant_cfg, "products") and hasattr(tenant_cfg.products, "features"):
                product_schema_cols.update(f.name for f in tenant_cfg.products.features)
            cols_to_keep = [c for c in active_cat_df.columns if c in product_schema_cols or c in ("brand", "price")]
            products = active_cat_df[cols_to_keep].copy()

        current_dataset = {
            "customers": len(customers),
            "products": len(products),
            "interactions": len(interactions),
            "products_added_from_interactions": products_added_from_interactions,
        }
        update_progress(
            "adapting_data",
            f"Built tables successfully for '{tenant_id}': "
            f"customers={len(customers):,} rows, "
            f"products={len(products):,} rows, "
            f"interactions={len(interactions):,} rows",
        )

        # Write processed data via storage
        prefix_data = f"data/processed/{tenant_id}"
        storage.write_file(
            f"{prefix_data}/customers.csv",
            customers.to_csv(index=False).encode("utf-8"),
        )
        storage.write_file(
            f"{prefix_data}/products.csv",
            products.to_csv(index=False).encode("utf-8"),
        )
        storage.write_file(
            f"{prefix_data}/interactions.csv",
            interactions.to_csv(index=False).encode("utf-8"),
        )
        logger.info(
            "[%s] Wrote tenant '%s' tables via %s to %s",
            tenant_id,
            tenant_id,
            type(storage).__name__,
            prefix_data,
        )

        # Stage 2: Splitting Data
        update_progress("splitting_data", "Creating train/test split for evaluation...")
        feature_columns = [f.name for f in tenant_cfg.customers.features]
        ranking_specs = tenant_cfg.customers.features
        if not feature_columns:
            logger.info("[%s] No customer features defined in config; deriving behavioral features", tenant_id)
            cust_counts = interactions["customer_id"].value_counts()
            customers["interaction_count"] = customers["customer_id"].map(cust_counts).fillna(0).astype(float)
            feature_columns = ["interaction_count"]
            from src.core.schema import FeatureSpec
            ranking_specs = [FeatureSpec(name="interaction_count", dtype="numeric")]

        train_interactions, test_interactions = create_train_test_split(
            interactions, max_test_items_per_customer=2, random_state=42
        )

        customer_lookup = customers.set_index("customer_id")
        customer_ids = sorted(test_interactions["customer_id"].drop_duplicates())
        if len(customer_ids) > 100:
            customer_ids = customer_ids[:100]

        # Stage 3: Candidate Models Training & Evaluation
        # 1. Content-Based
        models_state["content"] = "training"
        update_progress("training_content", "Training 1/4: ContentBasedRecommender...")
        try:
            content_model = ContentBasedRecommender().fit(
                customers, train_interactions, feature_columns
            )
            models_state["content"] = "evaluating"
            update_progress("evaluating_content", "Evaluating 1/4: ContentBasedRecommender on holdout...")
            cb_rows: list[dict[str, float]] = []
            for cid in customer_ids:
                relevant = set(
                    test_interactions.loc[test_interactions["customer_id"] == cid, "product_id"]
                )
                if not relevant or cid not in customer_lookup.index:
                    continue
                recs = content_model.recommend(customer_lookup.loc[cid], top_k=5)
                cb_rows.append(evaluate_all(recs, relevant, k=5))

            if cb_rows:
                metrics_state["content"] = {
                    "ndcg": round(sum(r["ndcg@5"] for r in cb_rows) / len(cb_rows), 4),
                    "precision": round(sum(r["precision@5"] for r in cb_rows) / len(cb_rows), 4),
                    "recall": round(sum(r["recall@5"] for r in cb_rows) / len(cb_rows), 4),
                }
            else:
                metrics_state["content"] = {"ndcg": 0.0, "precision": 0.0, "recall": 0.0}
            models_state["content"] = "done"
        except Exception as exc:
            logger.warning("[%s] ContentBased candidate model failed: %s", tenant_id, exc)
            models_state["content"] = "failed"
            metrics_state["content"] = {"ndcg": 0.0, "precision": 0.0, "recall": 0.0}

        # 2. Collaborative Filtering
        models_state["collaborative"] = "training"
        update_progress("training_collaborative", "Training 2/4: CollaborativeFilteringRecommender...")
        try:
            cf_model = CollaborativeFilteringRecommender(n_factors=5).fit(train_interactions)
            models_state["collaborative"] = "evaluating"
            update_progress("evaluating_collaborative", "Evaluating 2/4: CollaborativeFilteringRecommender on holdout...")
            cf_rows: list[dict[str, float]] = []
            for cid in customer_ids:
                relevant = set(
                    test_interactions.loc[test_interactions["customer_id"] == cid, "product_id"]
                )
                if not relevant:
                    continue
                recs = cf_model.recommend(cid, top_k=5)
                cf_rows.append(evaluate_all(recs, relevant, k=5))

            if cf_rows:
                metrics_state["collaborative"] = {
                    "ndcg": round(sum(r["ndcg@5"] for r in cf_rows) / len(cf_rows), 4),
                    "precision": round(sum(r["precision@5"] for r in cf_rows) / len(cf_rows), 4),
                    "recall": round(sum(r["recall@5"] for r in cf_rows) / len(cf_rows), 4),
                }
            else:
                metrics_state["collaborative"] = {"ndcg": 0.0, "precision": 0.0, "recall": 0.0}
            models_state["collaborative"] = "done"
        except Exception as exc:
            logger.warning("[%s] CollaborativeFiltering candidate model failed: %s", tenant_id, exc)
            models_state["collaborative"] = "failed"
            metrics_state["collaborative"] = {"ndcg": 0.0, "precision": 0.0, "recall": 0.0}

        # 3. Dynamic Hybrid
        models_state["hybrid"] = "training"
        update_progress("training_hybrid", "Training 3/4: HybridRecommender...")
        try:
            hybrid_model = HybridRecommender().fit(
                customers, train_interactions, feature_columns
            )
            models_state["hybrid"] = "evaluating"
            update_progress("evaluating_hybrid", "Evaluating 3/4: HybridRecommender on holdout...")
            hy_rows: list[dict[str, float]] = []
            for cid in customer_ids:
                relevant = set(
                    test_interactions.loc[test_interactions["customer_id"] == cid, "product_id"]
                )
                if not relevant or cid not in customer_lookup.index:
                    continue
                recs = hybrid_model.recommend(cid, customer_lookup.loc[cid], top_k=5)
                hy_rows.append(evaluate_all(recs, relevant, k=5))

            if hy_rows:
                metrics_state["hybrid"] = {
                    "ndcg": round(sum(r["ndcg@5"] for r in hy_rows) / len(hy_rows), 4),
                    "precision": round(sum(r["precision@5"] for r in hy_rows) / len(hy_rows), 4),
                    "recall": round(sum(r["recall@5"] for r in hy_rows) / len(hy_rows), 4),
                }
            else:
                metrics_state["hybrid"] = {"ndcg": 0.0, "precision": 0.0, "recall": 0.0}
            models_state["hybrid"] = "done"
        except Exception as exc:
            logger.warning("[%s] Hybrid candidate model failed: %s", tenant_id, exc)
            models_state["hybrid"] = "failed"
            metrics_state["hybrid"] = {"ndcg": 0.0, "precision": 0.0, "recall": 0.0}

        # 4. Learned Ranking (XGBoost)
        models_state["xgboost"] = "training"
        update_progress("training_xgboost", "Training 4/4: LearnedRankingRecommender...")
        try:
            ranking_model = LearnedRankingRecommender(
                customer_specs=ranking_specs
            ).fit(customers, train_interactions, products)
            models_state["xgboost"] = "evaluating"
            update_progress("evaluating_xgboost", "Evaluating 4/4: LearnedRankingRecommender on holdout...")
            rk_rows: list[dict[str, float]] = []
            for cid in customer_ids:
                relevant = set(
                    test_interactions.loc[test_interactions["customer_id"] == cid, "product_id"]
                )
                if not relevant:
                    continue
                recs = ranking_model.recommend(cid, top_k=5)
                rk_rows.append(evaluate_all(recs, relevant, k=5))

            if rk_rows:
                metrics_state["xgboost"] = {
                    "ndcg": round(sum(r["ndcg@5"] for r in rk_rows) / len(rk_rows), 4),
                    "precision": round(sum(r["precision@5"] for r in rk_rows) / len(rk_rows), 4),
                    "recall": round(sum(r["recall@5"] for r in rk_rows) / len(rk_rows), 4),
                }
            else:
                metrics_state["xgboost"] = {"ndcg": 0.0, "precision": 0.0, "recall": 0.0}
            models_state["xgboost"] = "done"
        except Exception as exc:
            logger.warning("[%s] LearnedRanking candidate model failed: %s", tenant_id, exc)
            models_state["xgboost"] = "failed"
            metrics_state["xgboost"] = {"ndcg": 0.0, "precision": 0.0, "recall": 0.0}

        # Stage 4: Winner Selection
        valid_candidates = [k for k in MODEL_KEYS if models_state[k] == "done"]
        if not valid_candidates:
            raise RuntimeError("All candidate recommendation models failed in tournament.")

        current_winner_key = max(valid_candidates, key=lambda k: metrics_state[k]["ndcg"])
        current_winner_model = DISPLAY_NAMES[current_winner_key]

        logger.info(
            "Tenant '%s' evaluation complete. Scores: %s",
            tenant_id,
            metrics_state,
        )
        logger.info(
            "Winning model for tenant '%s': %s (%s)",
            tenant_id,
            current_winner_key,
            current_winner_model,
        )

        update_progress(
            "refitting_winner",
            f"Tournament finished. Refitting winner '{current_winner_model}' on full dataset...",
        )

        if current_winner_key == "content":
            winning_model_instance = ContentBasedRecommender().fit(
                customers, interactions, feature_columns
            )
        elif current_winner_key == "collaborative":
            winning_model_instance = CollaborativeFilteringRecommender(n_factors=5).fit(
                interactions
            )
        elif current_winner_key == "hybrid":
            winning_model_instance = HybridRecommender().fit(
                customers, interactions, feature_columns
            )
        else:
            winning_model_instance = LearnedRankingRecommender(
                customer_specs=ranking_specs
            ).fit(customers, interactions, products)

        winning_model_instance.customers_ = customers
        winning_model_instance.products_ = products

        # Stage 5: Save Winning Model Artifact
        current_model_path = f"models/{tenant_id}/final_model.joblib"
        update_progress("persisting_model", f"Saving winning model to {current_model_path}...")
        saved_path = save_model(winning_model_instance, current_model_path, storage=storage)
        logger.info("Saved winning model for tenant '%s' to %s", tenant_id, saved_path)

        # Stage 6: Artifact Verification
        update_progress("verifying", "Verifying saved artifacts and storage integrity...")
        required_artifacts = [
            f"data/processed/{tenant_id}/customers.csv",
            f"data/processed/{tenant_id}/products.csv",
            f"data/processed/{tenant_id}/interactions.csv",
            current_model_path,
        ]
        for art_path in required_artifacts:
            if not storage.exists(art_path):
                raise RuntimeError(
                    f"Artifact verification failed: missing '{art_path}' in storage."
                )

        loaded_test_model = load_model(current_model_path, storage=storage)
        if loaded_test_model is None:
            raise RuntimeError(
                f"Artifact verification failed: failed to deserialize '{current_model_path}'."
            )

        clear_model_cache()
        from src.catalog.active_set import clear_active_catalog_cache
        clear_active_catalog_cache(tenant_id)

        # Stage 7: Complete - Write trained products marker
        trained_pids = sorted(products["product_id"].astype(str).unique().tolist())
        trained_at_iso = datetime.now(timezone.utc).isoformat()
        current_trained_count = len(trained_pids)
        current_trained_at = trained_at_iso

        storage.write_file(
            f"models/{tenant_id}/trained_products.json",
            json.dumps(trained_pids, indent=2).encode("utf-8"),
        )

        final_state = update_progress(
            stage="completed",
            message=f"Model tournament successfully completed. Winner: {current_winner_model}.",
            status_val="completed",
            ready=True,
        )
        return final_state

    except MemoryError as mem_err:
        err_msg = "dataset is too large for this server's memory"
        for k in MODEL_KEYS:
            if models_state[k] in ("training", "evaluating"):
                models_state[k] = "failed"
        update_progress(
            stage="failed",
            message=f"Training failed: {err_msg}",
            status_val="failed",
            error=err_msg,
            ready=False,
        )
        raise RuntimeError(err_msg) from mem_err
    except Exception as exc:
        err_msg = str(exc)
        for k in MODEL_KEYS:
            if models_state[k] in ("training", "evaluating"):
                models_state[k] = "failed"
        update_progress(
            stage="failed",
            message=f"Training failed: {err_msg}",
            status_val="failed",
            error=err_msg,
            ready=False,
        )
        raise
