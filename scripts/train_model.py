"""Train and persist the shipped recommendation model for a given tenant.

Usage:
    python scripts/train_model.py --tenant_id telco_default
    python scripts/train_model.py --tenant_id fixture_ecommerce
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running as `python scripts/train_model.py` from the project root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# pyrefly: ignore [missing-import]
from src.data.adapters.generic_config_adapter import GenericConfigAdapter

# pyrefly: ignore [missing-import]
from src.models.ranking_model import LearnedRankingRecommender
from src.storage import get_storage_backend

# pyrefly: ignore [missing-import]
from src.utils.config import get_tenant_config, load_config

# pyrefly: ignore [missing-import]
from src.utils.logger import get_logger

# pyrefly: ignore [missing-import]
from src.utils.persistence import save_model

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train recommendation model for a specific tenant."
    )
    parser.add_argument(
        "--tenant_id",
        type=str,
        default=os.environ.get("TENANT_ID", "telco_default"),
        help="Tenant ID to train model for (default: $TENANT_ID or telco_default)",
    )
    args = parser.parse_args()

    config = load_config()
    storage = get_storage_backend(config)
    tenant_cfg = get_tenant_config(config, args.tenant_id)
    adapter = GenericConfigAdapter(tenant_cfg, storage=storage)

    customers, products, interactions = adapter.run()

    final_model = LearnedRankingRecommender(
        customer_specs=tenant_cfg.customers.features
    ).fit(
        customers,
        interactions,
        products,
    )

    model_path = f"models/{args.tenant_id}/final_model.joblib"
    saved_path = save_model(final_model, model_path, storage=storage)
    logger.info(
        f"Saved trained model for tenant '{args.tenant_id}' to {saved_path}"
    )


if __name__ == "__main__":
    main()