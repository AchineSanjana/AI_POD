"""Train and persist the shipped recommendation model.

This script rebuilds the processed Telco tables, fits the learned ranking
recommender, and saves the trained artifact to models/final_model.joblib.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python scripts/train_model.py` from the project root.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.data.reshape_telco import run as build_processed_tables
from src.models.ranking_model import LearnedRankingRecommender
from src.utils.config import load_config
from src.utils.logger import get_logger
from src.utils.persistence import save_model

logger = get_logger(__name__)


def main() -> None:
    config = load_config()
    tables = build_processed_tables(config)

    final_model = LearnedRankingRecommender().fit(
        tables["customers"],
        tables["interactions"],
        tables["products"],
    )

    model_path = save_model(final_model, Path("models") / "final_model.joblib")
    logger.info(f"Saved final model to {model_path}")


if __name__ == "__main__":
    main()